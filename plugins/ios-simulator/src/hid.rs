//! Touches, keys and buttons sent straight to a simulator, the way Simulator.app sends
//! them: CoreSimulator finds the device, SimulatorKit builds Indigo HID messages and its
//! `SimDeviceLegacyHIDClient` delivers them. Both are Xcode's private frameworks, loaded
//! at run time, so nothing beyond Xcode needs installing.
//!
//! The signatures below were read off Xcode 26.2's SimulatorKit (arm64e): a change in a
//! later Xcode fails here with an error, never with a touch somewhere else, since every
//! symbol and class is looked up by name and checked before use.

use std::{
    collections::HashMap,
    ffi::{CStr, CString, c_char, c_int, c_void},
    path::Path,
    sync::Mutex,
};

use anyhow::{Context, Result, bail, ensure};
use phone_kit::Phase;

type Id = *mut c_void;
type Sel = *mut c_void;

#[repr(C)]
#[derive(Clone, Copy)]
struct CgPoint {
    x: f64,
    y: f64,
}

#[link(name = "objc")]
unsafe extern "C" {
    fn objc_getClass(name: *const c_char) -> Id;
    fn sel_registerName(name: *const c_char) -> Sel;
    fn objc_msgSend();
    fn objc_autoreleasePoolPush() -> *mut c_void;
    fn objc_autoreleasePoolPop(pool: *mut c_void);
}

unsafe extern "C" {
    fn dlopen(path: *const c_char, mode: c_int) -> *mut c_void;
    fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
}

const RTLD_NOW: c_int = 2;
const CORE_SIMULATOR: &str =
    "/Library/Developer/PrivateFrameworks/CoreSimulator.framework/CoreSimulator";
const SIMULATOR_KIT: &str = "Library/PrivateFrameworks/SimulatorKit.framework/SimulatorKit";

/// The main screen's touch target, as Simulator.app addresses it.
const SCREEN_TARGET: u32 = 0x32;
/// The hardware buttons' target.
const BUTTON_TARGET: u32 = 0x33;
/// NSEvent types the touch builder takes.
const MOUSE_DOWN: u64 = 1;
const MOUSE_UP: u64 = 2;
const MOUSE_DRAGGED: u64 = 6;
const KEY_DOWN: u32 = 1;
const KEY_UP: u32 = 2;

/// Where a touch starts from: the bottom edge is the home gesture.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Edge {
    #[default]
    None = 0,
    Bottom = 3,
}

type MouseFn = unsafe extern "C" fn(*const CgPoint, *const CgPoint, u32, u64, u64, f64, f64) -> Id;
type KeyFn = unsafe extern "C" fn(u32, u32) -> Id;
type ButtonFn = unsafe extern "C" fn(u32, u32, u32) -> Id;

struct Kit {
    mouse: MouseFn,
    key: KeyFn,
    button: ButtonFn,
}

/// A client per device, kept while the plugin runs: making one costs a round trip to
/// CoreSimulator.
struct Client(Id);
// SAFETY: the client is an Objective-C object whose `send` is safe from any thread; it is
// never released, so the pointer stays valid.
unsafe impl Send for Client {}

pub struct Hid {
    kit: Kit,
    developer: CString,
    clients: Mutex<HashMap<String, Client>>,
}

impl Hid {
    /// Loads the frameworks of the Xcode at `developer` (`xcode-select -p`).
    pub fn load(developer: &Path) -> Result<Self> {
        let developer_str = developer.to_str().context("an odd developer folder")?;
        let kit_path = format!("{developer_str}/{SIMULATOR_KIT}");
        // SAFETY: dlopen and dlsym take NUL-terminated paths; the functions are cast to
        // the signatures read off the framework.
        unsafe {
            open(CORE_SIMULATOR)?;
            let kit = open(&kit_path)?;
            let kit = Kit {
                mouse: std::mem::transmute::<*mut c_void, MouseFn>(symbol(
                    kit,
                    "IndigoHIDMessageForMouseNSEvent",
                )?),
                key: std::mem::transmute::<*mut c_void, KeyFn>(symbol(
                    kit,
                    "IndigoHIDMessageForKeyboardArbitrary",
                )?),
                button: std::mem::transmute::<*mut c_void, ButtonFn>(symbol(
                    kit,
                    "IndigoHIDMessageForButton",
                )?),
            };
            Ok(Self {
                kit,
                developer: CString::new(developer_str)?,
                clients: Mutex::new(HashMap::new()),
            })
        }
    }

    /// One phase of a touch at `x`, `y` on a screen `size` points across.
    pub fn touch(
        &self,
        udid: &str,
        phase: Phase,
        (x, y): (f64, f64),
        size: (u32, u32),
        edge: Edge,
    ) -> Result<()> {
        let kind = match phase {
            Phase::Down => MOUSE_DOWN,
            Phase::Move => MOUSE_DRAGGED,
            Phase::Up => MOUSE_UP,
        };
        let point = CgPoint { x, y };
        // SAFETY: the builder reads one point and returns a calloc'ed message or null.
        let message = unsafe {
            (self.kit.mouse)(
                &point,
                std::ptr::null(),
                SCREEN_TARGET,
                kind,
                edge as u64,
                f64::from(size.0),
                f64::from(size.1),
            )
        };
        // The builder drops moves closer than a frame apart: not an error.
        if message.is_null() && phase == Phase::Move {
            return Ok(());
        }
        self.send(udid, message)
    }

    /// A key by its HID usage, pressed or let go.
    pub fn key(&self, udid: &str, usage: u32, down: bool) -> Result<()> {
        let direction = if down { KEY_DOWN } else { KEY_UP };
        // SAFETY: plain integers in, a message or null out.
        let message = unsafe { (self.kit.key)(usage, direction) };
        self.send(udid, message)
    }

    /// A hardware button by its event source, pressed or let go.
    pub fn button(&self, udid: &str, source: u32, down: bool) -> Result<()> {
        let direction = if down { KEY_DOWN } else { KEY_UP };
        // SAFETY: as `key`.
        let message = unsafe { (self.kit.button)(source, direction, BUTTON_TARGET) };
        self.send(udid, message)
    }

    fn send(&self, udid: &str, message: Id) -> Result<()> {
        ensure!(!message.is_null(), "SimulatorKit made no message");
        let mut clients = self
            .clients
            .lock()
            .map_err(|_| anyhow::anyhow!("the device clients are poisoned"))?;
        let client = match clients.get(udid) {
            Some(client) => client.0,
            None => {
                let client = self.client(udid)?;
                clients.insert(udid.to_owned(), Client(client));
                client
            }
        };
        // SAFETY: `sendWithMessage:freeWhenDone:completionQueue:completion:` takes the
        // message, frees it once sent, and accepts no queue and no completion.
        unsafe {
            let send: unsafe extern "C" fn(Id, Sel, Id, bool, Id, Id) =
                std::mem::transmute(objc_msgSend as unsafe extern "C" fn());
            send(
                client,
                sel("sendWithMessage:freeWhenDone:completionQueue:completion:"),
                message,
                true,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            );
        }
        Ok(())
    }

    /// A new HID client for the device `udid`, found in the default device set.
    fn client(&self, udid: &str) -> Result<Id> {
        // SAFETY: every message goes to an object of the class that answers it, with the
        // argument types of its selector; returned objects are checked for null.
        unsafe {
            let pool = objc_autoreleasePoolPush();
            let found = self.find_client(udid);
            objc_autoreleasePoolPop(pool);
            found
        }
    }

    unsafe fn find_client(&self, udid: &str) -> Result<Id> {
        unsafe {
            let msg_id: unsafe extern "C" fn(Id, Sel) -> Id =
                std::mem::transmute(objc_msgSend as unsafe extern "C" fn());
            let msg_ptr_err: unsafe extern "C" fn(Id, Sel, *const c_char) -> Id =
                std::mem::transmute(objc_msgSend as unsafe extern "C" fn());
            let msg_id_err: unsafe extern "C" fn(Id, Sel, Id, *mut Id) -> Id =
                std::mem::transmute(objc_msgSend as unsafe extern "C" fn());
            let msg_err: unsafe extern "C" fn(Id, Sel, *mut Id) -> Id =
                std::mem::transmute(objc_msgSend as unsafe extern "C" fn());
            let msg_index: unsafe extern "C" fn(Id, Sel, usize) -> Id =
                std::mem::transmute(objc_msgSend as unsafe extern "C" fn());
            let msg_count: unsafe extern "C" fn(Id, Sel) -> usize =
                std::mem::transmute(objc_msgSend as unsafe extern "C" fn());
            let msg_utf8: unsafe extern "C" fn(Id, Sel) -> *const c_char =
                std::mem::transmute(objc_msgSend as unsafe extern "C" fn());

            let string = msg_ptr_err(
                class("NSString")?,
                sel("stringWithUTF8String:"),
                self.developer.as_ptr(),
            );
            ensure!(!string.is_null(), "cannot name the developer folder");
            let mut error: Id = std::ptr::null_mut();
            let context = msg_id_err(
                class("SimServiceContext")?,
                sel("sharedServiceContextForDeveloperDir:error:"),
                string,
                &mut error,
            );
            ensure!(!context.is_null(), "CoreSimulator does not answer");
            let set = msg_err(context, sel("defaultDeviceSetWithError:"), &mut error);
            ensure!(!set.is_null(), "no simulator device set");
            let devices = msg_id(set, sel("devices"));
            ensure!(!devices.is_null(), "no simulator devices");
            let mut device = std::ptr::null_mut();
            for index in 0..msg_count(devices, sel("count")) {
                let candidate = msg_index(devices, sel("objectAtIndex:"), index);
                let uuid = msg_id(candidate, sel("UDID"));
                if uuid.is_null() {
                    continue;
                }
                let text = msg_utf8(msg_id(uuid, sel("UUIDString")), sel("UTF8String"));
                if !text.is_null() && CStr::from_ptr(text).to_bytes() == udid.as_bytes() {
                    device = candidate;
                    break;
                }
            }
            ensure!(!device.is_null(), "no simulator device {udid}");
            let alloc = msg_id(
                class("_TtC12SimulatorKit24SimDeviceLegacyHIDClient")?,
                sel("alloc"),
            );
            let client = msg_id_err(alloc, sel("initWithDevice:error:"), device, &mut error);
            if client.is_null() {
                bail!("cannot reach the device's input; is it booted?");
            }
            Ok(client)
        }
    }
}

unsafe fn open(path: &str) -> Result<*mut c_void> {
    let path = CString::new(path)?;
    // SAFETY: a NUL-terminated path.
    let handle = unsafe { dlopen(path.as_ptr(), RTLD_NOW) };
    ensure!(
        !handle.is_null(),
        "cannot load {}: is Xcode installed?",
        path.to_string_lossy()
    );
    Ok(handle)
}

unsafe fn symbol(handle: *mut c_void, name: &str) -> Result<*mut c_void> {
    let name_c = CString::new(name)?;
    // SAFETY: a handle from dlopen and a NUL-terminated name.
    let found = unsafe { dlsym(handle, name_c.as_ptr()) };
    ensure!(!found.is_null(), "this Xcode has no {name}");
    Ok(found)
}

fn class(name: &str) -> Result<Id> {
    let name_c = CString::new(name)?;
    // SAFETY: a NUL-terminated name; null when the class is not loaded.
    let found = unsafe { objc_getClass(name_c.as_ptr()) };
    ensure!(!found.is_null(), "this Xcode has no {name}");
    Ok(found)
}

fn sel(name: &str) -> Sel {
    let name_c = CString::new(name).unwrap_or_default();
    // SAFETY: a NUL-terminated name; selectors are interned and never freed.
    unsafe { sel_registerName(name_c.as_ptr()) }
}
