# SMA EMS Module

## Introduction

The SMA EMS module allows fetching of solar Generation and overall Consumption values from SMA inverters that support the Webconnect API.

## Configuration

The following table shows the available configuration parameters for the openHAB EMS module.

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
