//! What the phone plugins share: a [`Phone`] a backend implements, and the two front
//! ends over it.
//!
//! - `phone`: the trait, its devices and buttons;
//! - `panel`: the program behind the window's panel, over duskcode's ui wire;
//! - `mcp`: the agent's tool, an MCP server on stdio;
//! - `picture`: a screen scaled to points for the model;
//! - `run`: programs without a shell, with a time and size limit;
//! - `lines`: reading one line of untrusted input, capped.

pub mod lines;
pub mod mcp;
pub mod panel;
pub mod phone;
pub mod picture;
pub mod run;

pub use phone::{Button, Device, Phone, Setup};
