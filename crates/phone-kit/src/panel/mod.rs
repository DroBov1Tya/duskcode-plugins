//! The program behind the phone panel: it reads the core's messages on stdin and
//! answers with views and the screen's frames on stdout. A device's screen streams only
//! while the panel is open and the chosen device runs; slow work (starting, touching)
//! runs aside, so frames keep coming.
//!
//! - `wire`: the messages and widgets;
//! - `view`: the view drawn from the state.

mod view;
pub mod wire;

use std::{future::pending, sync::Arc};

use anyhow::Result;
use base64::{Engine, engine::general_purpose::STANDARD};
use tokio::{
    io::{AsyncWriteExt, BufReader},
    sync::mpsc,
    task::JoinHandle,
};

use crate::{Button, Device, Phone, Setup, lines, picture::is_jpeg};
use wire::{FromPlugin, MAX_FRAME, MAX_IN, MAX_LINE, ToPlugin, UiEvent};

/// The widget the frames are for.
const SCREEN: &str = "screen";
/// The longest note shown for a failed action.
const MAX_NOTICE: usize = 300;

/// What the view is drawn from.
pub struct State {
    pub title: &'static str,
    pub setup: Setup,
    pub devices: Vec<Device>,
    /// The device shown, by id.
    pub chosen: Option<String>,
    /// What is being done to the device, said in place of its screen.
    pub busy: Option<&'static str>,
    pub error: Option<String>,
    /// The chosen device's screen in points, once read.
    pub size: Option<(u32, u32)>,
    /// The devices were looked at once.
    pub looked: bool,
}

impl State {
    pub fn chosen_device(&self) -> Option<&Device> {
        let chosen = self.chosen.as_ref()?;
        self.devices.iter().find(|device| &device.id == chosen)
    }
}

/// Work that ran aside, back in the loop.
enum Done {
    Looked(Setup, Result<Vec<Device>>),
    Acted {
        error: Option<String>,
        busy: bool,
        look: bool,
    },
    Sized(String, Result<(u32, u32)>),
    StreamEnded(u64, String),
}

struct Stream {
    device: String,
    generation: u64,
    frames: mpsc::Receiver<Vec<u8>>,
    task: JoinHandle<()>,
}

impl Drop for Stream {
    fn drop(&mut self) {
        // Dropping the backend's work also ends a child it started, such as AXe.
        self.task.abort();
    }
}

/// Runs the panel until the core closes stdin.
pub async fn run<P: Phone>(phone: P) -> Result<()> {
    let (lines_in, mut lines) = mpsc::channel(16);
    tokio::spawn(read_stdin(lines_in));
    let (done_in, mut done) = mpsc::channel(16);
    let mut panel = Panel::new(phone, done_in);
    let mut stdout = tokio::io::stdout();
    loop {
        tokio::select! {
            line = lines.recv() => match line {
                Some(line) => panel.on_line(&line),
                None => break,
            },
            Some(event) = done.recv() => panel.on_done(event),
            Some(frame) = next_frame(&mut panel.stream) => panel.on_frame(frame),
        }
        for line in panel.out.drain(..) {
            stdout.write_all(line.as_bytes()).await?;
            stdout.write_all(b"\n").await?;
        }
        stdout.flush().await?;
    }
    Ok(())
}

/// Lines from the core, read aside since a capped read cannot be cancelled midway.
async fn read_stdin(lines: mpsc::Sender<Vec<u8>>) {
    let mut stdin = BufReader::new(tokio::io::stdin());
    loop {
        match lines::read_line(&mut stdin, MAX_IN).await {
            Ok(Some(line)) => {
                if lines.send(line).await.is_err() {
                    return;
                }
            }
            Ok(None) => return,
            Err(error) => {
                eprintln!("stdin: {error:#}");
                return;
            }
        }
    }
}

async fn next_frame(stream: &mut Option<Stream>) -> Option<Vec<u8>> {
    match stream {
        Some(stream) => stream.frames.recv().await,
        None => pending().await,
    }
}

struct Panel<P> {
    phone: Arc<P>,
    state: State,
    /// The open part, which views and frames are sent for.
    part: Option<String>,
    stream: Option<Stream>,
    generation: u64,
    /// The device whose screen size is in `state.size`.
    sized: Option<String>,
    /// A device whose stream failed; it is not restarted until the user acts.
    stalled: Option<String>,
    done: mpsc::Sender<Done>,
    /// Lines to write, each one JSON object.
    out: Vec<String>,
}

impl<P: Phone> Panel<P> {
    fn new(phone: P, done: mpsc::Sender<Done>) -> Self {
        let title = phone.title();
        Self {
            phone: Arc::new(phone),
            state: State {
                title,
                setup: Setup::default(),
                devices: Vec::new(),
                chosen: None,
                busy: None,
                error: None,
                size: None,
                looked: false,
            },
            part: None,
            stream: None,
            generation: 0,
            sized: None,
            stalled: None,
            done,
            out: Vec::new(),
        }
    }

    fn on_line(&mut self, line: &[u8]) {
        let message = match serde_json::from_slice::<ToPlugin>(line) {
            Ok(message) => message,
            // A message of a newer core is skipped, not fatal.
            Err(error) => return eprintln!("a message not understood: {error}"),
        };
        match message {
            ToPlugin::Open { part } => {
                self.part = Some(part);
                self.render();
                self.look();
            }
            ToPlugin::Close { part } => {
                if self.part.as_ref() == Some(&part) {
                    self.part = None;
                    self.stream = None;
                }
            }
            ToPlugin::Event {
                part,
                widget,
                event,
            } => {
                if self.part.as_ref() == Some(&part) {
                    self.on_event(&widget, event);
                }
            }
        }
    }

    fn on_event(&mut self, widget: &str, event: UiEvent) {
        if self.state.busy.is_some() {
            return;
        }
        let running = self
            .state
            .chosen_device()
            .is_some_and(|device| device.running);
        match (widget, event) {
            ("device", UiEvent::Select { item }) => {
                if self.state.devices.iter().any(|device| device.id == item) {
                    self.state.chosen = Some(item);
                    self.state.error = None;
                    self.stalled = None;
                    self.sync();
                    self.render();
                }
            }
            ("refresh", UiEvent::Click) => {
                self.stalled = None;
                self.state.error = None;
                self.look();
            }
            ("start", UiEvent::Click) if !running => {
                self.stalled = None;
                self.act(Some("Starting"), true, |phone, id| async move {
                    phone.start(&id).await
                });
            }
            ("stop", UiEvent::Click) if running => {
                self.stream = None;
                self.act(Some("Shutting down"), true, |phone, id| async move {
                    phone.stop(&id).await
                });
            }
            ("home", UiEvent::Click) if running => {
                self.act(None, false, |phone, id| async move {
                    phone.button(&id, Button::Home).await
                });
            }
            ("lock", UiEvent::Click) if running => {
                self.act(None, false, |phone, id| async move {
                    phone.button(&id, Button::Lock).await
                });
            }
            (SCREEN, UiEvent::Tap { x, y }) if running => {
                self.act(None, false, move |phone, id| async move {
                    phone.tap(&id, x, y).await
                });
            }
            (SCREEN, UiEvent::Swipe { from, to }) if running => {
                self.act(None, false, move |phone, id| async move {
                    phone.swipe(&id, from, to).await
                });
            }
            _ => {}
        }
    }

    fn on_done(&mut self, done: Done) {
        match done {
            Done::Looked(setup, devices) => {
                self.state.looked = true;
                self.state.setup = setup;
                match devices {
                    Ok(devices) => self.state.devices = devices,
                    Err(error) => {
                        self.state.devices.clear();
                        if self.state.setup.blocker.is_none() {
                            self.state.error = Some(format!("{error:#}"));
                        }
                    }
                }
                self.choose();
                self.sync();
                self.render();
            }
            Done::Acted { error, busy, look } => {
                if busy {
                    self.state.busy = None;
                    self.state.error = error;
                    self.render();
                } else if let Some(error) = error {
                    let text = error.chars().take(MAX_NOTICE).collect();
                    self.send(&FromPlugin::Notice { text });
                }
                if look {
                    self.look();
                }
            }
            Done::Sized(device, size) => {
                if self.state.chosen.as_ref() != Some(&device) {
                    return;
                }
                match size {
                    Ok(size) => {
                        self.state.size = Some(size);
                        self.sized = Some(device);
                    }
                    Err(error) => self.state.error = Some(format!("{error:#}")),
                }
                self.render();
            }
            Done::StreamEnded(generation, why) => {
                if self
                    .stream
                    .as_ref()
                    .is_none_or(|stream| stream.generation != generation)
                {
                    return;
                }
                let stream = self.stream.take();
                self.stalled = stream.map(|stream| stream.device.clone());
                self.state.error = Some(format!("The screen stopped: {why}"));
                self.render();
                // The device may have been shut down elsewhere.
                self.look();
            }
        }
    }

    fn on_frame(&mut self, jpeg: Vec<u8>) {
        let Some(part) = &self.part else { return };
        // The core refuses a frame past its limit, and base64 grows it by a third.
        if !is_jpeg(&jpeg) || jpeg.len() > MAX_FRAME || jpeg.len() / 3 * 4 > MAX_LINE - 1024 {
            return;
        }
        let message = FromPlugin::Frame {
            part,
            widget: SCREEN,
            jpeg: STANDARD.encode(&jpeg),
        };
        if let Ok(line) = serde_json::to_string(&message) {
            self.out.push(line);
        }
    }

    /// Keeps the chosen device when it is still there, else the first running one, else
    /// the first.
    fn choose(&mut self) {
        let devices = &self.state.devices;
        let kept = self
            .state
            .chosen
            .as_ref()
            .filter(|id| devices.iter().any(|device| &device.id == *id));
        let chosen = kept
            .cloned()
            .or_else(|| {
                devices
                    .iter()
                    .find(|device| device.running)
                    .map(|device| device.id.clone())
            })
            .or_else(|| devices.first().map(|device| device.id.clone()));
        if chosen != self.state.chosen {
            self.state.chosen = chosen;
            self.stalled = None;
        }
    }

    /// Streams the chosen device's screen while the panel is open and it runs, and
    /// reads its size once.
    fn sync(&mut self) {
        let device = self
            .state
            .chosen_device()
            .filter(|device| device.running)
            .map(|device| device.id.clone());
        if self.sized != self.state.chosen {
            self.state.size = None;
            self.sized = None;
        }
        let Some(id) = device.filter(|id| self.part.is_some() && self.stalled.as_ref() != Some(id))
        else {
            self.stream = None;
            return;
        };
        if self.sized.is_none() {
            let (phone, done, id) = (Arc::clone(&self.phone), self.done.clone(), id.clone());
            tokio::spawn(async move {
                let size = phone.size(&id).await;
                let _ = done.send(Done::Sized(id, size)).await;
            });
        }
        if self
            .stream
            .as_ref()
            .is_some_and(|stream| stream.device == id)
        {
            return;
        }
        self.generation += 1;
        let generation = self.generation;
        let (frames_in, frames) = mpsc::channel(1);
        let (phone, done, device) = (Arc::clone(&self.phone), self.done.clone(), id.clone());
        let task = tokio::spawn(async move {
            let why = match phone.watch(&device, frames_in).await {
                Ok(()) => "the stream ended".to_owned(),
                Err(error) => format!("{error:#}"),
            };
            let _ = done.send(Done::StreamEnded(generation, why)).await;
        });
        self.stream = Some(Stream {
            device: id,
            generation,
            frames,
            task,
        });
    }

    /// Looks at the setup and the devices aside.
    fn look(&mut self) {
        let (phone, done) = (Arc::clone(&self.phone), self.done.clone());
        tokio::spawn(async move {
            let (setup, devices) = tokio::join!(phone.setup(), phone.list());
            let _ = done.send(Done::Looked(setup, devices)).await;
        });
    }

    /// Does `work` to the chosen device aside; `busy` says so in place of its screen.
    fn act<F, W>(&mut self, busy: Option<&'static str>, look: bool, work: W)
    where
        W: FnOnce(Arc<P>, String) -> F,
        F: Future<Output = Result<()>> + Send + 'static,
    {
        let Some(id) = self.state.chosen.clone() else {
            return;
        };
        if busy.is_some() {
            self.state.busy = busy;
            self.state.error = None;
            self.render();
        }
        let work = work(Arc::clone(&self.phone), id);
        let done = self.done.clone();
        tokio::spawn(async move {
            let error = work.await.err().map(|error| format!("{error:#}"));
            let _ = done
                .send(Done::Acted {
                    error,
                    busy: busy.is_some(),
                    look,
                })
                .await;
        });
    }

    fn render(&mut self) {
        let Some(part) = &self.part else { return };
        let message = FromPlugin::View {
            part,
            root: view::render(&self.state),
        };
        if let Ok(line) = serde_json::to_string(&message) {
            self.out.push(line);
        }
    }

    fn send(&mut self, message: &FromPlugin) {
        if let Ok(line) = serde_json::to_string(message) {
            self.out.push(line);
        }
    }
}
