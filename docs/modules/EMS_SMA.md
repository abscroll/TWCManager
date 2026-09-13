# SMA EMS Module

## Introduction

The SMA EMS module allows fetching of solar Generation and overall Consumption values from SMA inverters that support the Webconnect API.

## Configuration

The following table shows the available configuration parameters for the SMA EMS module.

| Parameter   | Value         |
| ----------- | ------------- |
| enabled     | *required* Boolean value, `true` or `false`. Determines whether we will poll openHAB items. |
| url    | *required* The URL of the SMA Webconnect interface. |
| user | *required* The user group: user or installer |
| password  | *required* User password. |

### JSON Configuration Example

```
"SMA": {
  "enabled": true,
  "url": "https://192.168.12.3",
  "user": "user",
  "password" : "0000"
},
```

### Note
The consumption value is retrieved only if there is an SMA Energy Meter configured with the inverter.
# Library Compatibility

Python 3.12 and newer use pysma 1.1.6 or later (below 2.0), with
WebConnect sensor discovery. Older Python environments retain pysma 0.x.
The module uses grid_power, metering_power_supplied and
metering_power_absorbed for the existing generation/consumption calculation.

Optional SMA configuration fields:

* cacheTime: seconds between polling attempts, including failed attempts (default 10).
* timeout: total poll timeout in seconds, including login, discovery and logout (default 30).
* verifySSL: verify the inverter TLS certificate (default false, preserving existing behavior).

Failed or incomplete polls retain the previous readings; before the first
successful poll readings are zero. Cached readings can be stale during outages.
Test live readings before deploying to charger hardware.
