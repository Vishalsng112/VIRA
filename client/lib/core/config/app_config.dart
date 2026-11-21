const appName = 'VIRA Link';
const appVersion = '1.2.0';
const protocolVersion = 1;

/// How the app should choose its light or dark palette.
enum AppThemeMode { system, light, dark }

const defaultServerUrl = 'http://localhost:8000';
const defaultCaptureIntervalSeconds = 10;
const defaultSyncIntervalSeconds = 15;
const heartbeatIntervalSeconds = 30;
const maxBatchSize = 50;

const collectorDeviceStatus = 'device_status';
const collectorHardware = 'hardware_state';
const collectorNetwork = 'network_state';
const collectorAppUsage = 'app_usage';
const collectorScreenSession = 'screen_session';
const collectorBattery = 'battery_state';
const collectorActiveWindow = 'active_window';
const collectorDeviceHealth = 'device_health';
const collectorIdle = 'idle_state';
