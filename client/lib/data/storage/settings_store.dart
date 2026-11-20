import 'package:shared_preferences/shared_preferences.dart';

/// Non-secret client preferences. Secrets live in [CredentialStore].
class SettingsStore {
  SettingsStore._(this._prefs);

  static const _serverKey = 'settings.server_url';
  static const _deviceNameKey = 'settings.device_name';
  static const _autoSyncKey = 'settings.auto_sync';
  static const _captureKey = 'settings.capture_enabled';
  static const _intervalKey = 'settings.capture_interval_seconds';
  static const _collectorKey = 'settings.collector';

  static const defaultServerUrl = 'http://localhost:8000';
  static const defaultCaptureIntervalSeconds = 10;

  final SharedPreferences _prefs;

  static Future<SettingsStore> open() async =>
      SettingsStore._(await SharedPreferences.getInstance());

  String get serverUrl => _prefs.getString(_serverKey) ?? defaultServerUrl;
  Future<void> setServerUrl(String value) =>
      _prefs.setString(_serverKey, value.trim());

  String? get deviceName => _prefs.getString(_deviceNameKey);
  Future<void> setDeviceName(String value) =>
      _prefs.setString(_deviceNameKey, value.trim());

  bool get autoSync => _prefs.getBool(_autoSyncKey) ?? true;
  Future<void> setAutoSync(bool value) => _prefs.setBool(_autoSyncKey, value);

  bool get captureEnabled => _prefs.getBool(_captureKey) ?? true;
  Future<void> setCaptureEnabled(bool value) =>
      _prefs.setBool(_captureKey, value);

  int get captureIntervalSeconds =>
      _prefs.getInt(_intervalKey) ?? defaultCaptureIntervalSeconds;
  Future<void> setCaptureIntervalSeconds(int value) =>
      _prefs.setInt(_intervalKey, value);

  bool collectorEnabled(String id, {bool fallback = true}) =>
      _prefs.getBool('$_collectorKey.$id') ?? fallback;
  Future<void> setCollectorEnabled(String id, bool value) =>
      _prefs.setBool('$_collectorKey.$id', value);
}
