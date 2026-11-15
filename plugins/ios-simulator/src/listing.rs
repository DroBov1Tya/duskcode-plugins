//! What is installed: the iOS runtimes, their devices and the profiles of the device
//! types, read from `simctl list -j`.

use std::collections::HashMap;

use anyhow::{Context, Result};
use phone_kit::Device;
use serde::Deserialize;

use crate::run::{LIMIT, simctl};

#[derive(Deserialize)]
pub struct Listing {
    runtimes: Vec<ListedRuntime>,
    devices: HashMap<String, Vec<ListedDevice>>,
    #[serde(default)]
    devicetypes: Vec<ListedType>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ListedRuntime {
    identifier: String,
    name: String,
    #[serde(default)]
    is_available: bool,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ListedDevice {
    udid: String,
    name: String,
    state: String,
    #[serde(default)]
    is_available: bool,
    #[serde(default)]
    device_type_identifier: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ListedType {
    identifier: String,
    bundle_path: String,
}

pub async fn listing() -> Result<Listing> {
    let listing = simctl(&["list", "-j"], LIMIT).await?;
    serde_json::from_slice(&listing).context("simctl list gave no listing")
}

impl Listing {
    /// The names of the available iOS runtimes, such as "iOS 26.2".
    pub fn runtimes(&self) -> Vec<String> {
        let mut names: Vec<String> = self.ios_runtimes().into_values().collect();
        names.sort();
        names
    }

    /// The available devices of the available iOS runtimes: booted ones first, then
    /// newer runtimes, each runtime's devices in the order Xcode lists them.
    pub fn devices(&self) -> Vec<Device> {
        let runtimes = self.ios_runtimes();
        let mut devices: Vec<Device> = self
            .devices
            .iter()
            .filter_map(|(key, listed)| Some((runtimes.get(key)?, listed)))
            .flat_map(|(runtime, listed)| {
                listed
                    .iter()
                    .filter(|device| device.is_available)
                    .map(move |device| Device {
                        id: device.udid.clone(),
                        name: device.name.clone(),
                        detail: runtime.clone(),
                        running: device.state == "Booted",
                    })
            })
            .collect();
        devices.sort_by(|a, b| (b.running, &b.detail).cmp(&(a.running, &a.detail)));
        devices
    }

    /// Where Xcode keeps the profile of the device's type, which knows its screen.
    pub fn type_bundle(&self, udid: &str) -> Result<&str> {
        let kind = self
            .devices
            .values()
            .flatten()
            .find(|device| device.udid == udid)
            .map(|device| device.device_type_identifier.as_str())
            .context("the device is gone")?;
        self.devicetypes
            .iter()
            .find(|listed| listed.identifier == kind)
            .map(|listed| listed.bundle_path.as_str())
            .context("the device's type is unknown")
    }

    fn ios_runtimes(&self) -> HashMap<&String, String> {
        self.runtimes
            .iter()
            .filter(|runtime| runtime.is_available && runtime.name.starts_with("iOS "))
            .map(|runtime| (&runtime.identifier, runtime.name.clone()))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unavailable_runtimes_and_devices_are_left_out() {
        let listing: Listing = serde_json::from_str(
            r#"{
              "runtimes": [
                {"identifier": "r.ios", "name": "iOS 26.2", "isAvailable": true},
                {"identifier": "r.old", "name": "iOS 16.2", "isAvailable": false},
                {"identifier": "r.tv", "name": "tvOS 26.0", "isAvailable": true}
              ],
              "devices": {
                "r.ios": [
                  {"udid": "A", "name": "iPhone 17", "state": "Shutdown", "isAvailable": true, "deviceTypeIdentifier": "t.17"},
                  {"udid": "B", "name": "iPad", "state": "Booted", "isAvailable": true},
                  {"udid": "C", "name": "Broken", "state": "Shutdown", "isAvailable": false},
                  {"udid": "F", "name": "iPhone Air", "state": "Shutdown", "isAvailable": true}
                ],
                "r.old": [{"udid": "D", "name": "Old", "state": "Shutdown", "isAvailable": true}],
                "r.tv": [{"udid": "E", "name": "TV", "state": "Shutdown", "isAvailable": true}]
              },
              "devicetypes": [{"identifier": "t.17", "bundlePath": "/Profiles/iPhone 17.simdevicetype"}]
            }"#,
        )
        .unwrap();
        assert_eq!(listing.runtimes(), ["iOS 26.2"]);
        let devices = listing.devices();
        let udids: Vec<&str> = devices.iter().map(|device| device.id.as_str()).collect();
        assert_eq!(udids, ["B", "A", "F"]);
        assert!(devices[0].running && !devices[1].running);
        assert_eq!(
            listing.type_bundle("A").unwrap(),
            "/Profiles/iPhone 17.simdevicetype"
        );
        assert!(listing.type_bundle("B").is_err());
        assert!(listing.type_bundle("Z").is_err());
    }

    #[test]
    fn what_is_not_a_listing_is_refused() {
        assert!(serde_json::from_str::<Listing>("[]").is_err());
        assert!(serde_json::from_str::<Listing>(r#"{"runtimes": 1, "devices": {}}"#).is_err());
    }
}
