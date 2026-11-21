import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../../core/config/app_config.dart';
import '../../core/utils/ids.dart';

/// Non-secret client preferences. Secrets live in [CredentialStore].
class SettingsStore {
  SettingsStore._(this._prefs);

  static const _serverKey = 'settings.server_url';
  static const _deviceNameKey = 'settings.device_name';
  static const _autoSyncKey = 'settings.auto_sync';
  static const _captureKey = 'settings.capture_enabled';
  static const _intervalKey = 'settings.capture_interval_seconds';
  static const _collectorKey = 'settings.collector';
  static const _installationKey = 'settings.installation_id';
  static const _themeKey = 'settings.theme_mode';
  static const _diagnosticsKey = 'settings.diagnostics_enabled';
  static const _remindersKey = 'settings.break_reminders';
  static const _permissionSetupKey = 'settings.permission_setup_completed';
  static const _notificationPromptKey =
      'settings.notification_permission_prompted';
  static const _usageAccessDismissedKey = 'settings.usage_access_dismissed';
  static const _diagnosticEventsKey = 'settings.diagnostic_events';
  static const maxDiagnosticEvents = 12;

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

  /// Stable per-install identity. It survives sign-out and is sent on every
  /// enrollment so the server reuses the existing device row instead of
  /// registering the same machine again.
  String get installationId => _prefs.getString(_installationKey) ?? '';

  Future<String> ensureInstallationId() async {
    final existing = installationId;
    if (existing.isNotEmpty) return existing;
    final value = newUuidV4();
    await _prefs.setString(_installationKey, value);
    return value;
  }

  bool get autoSync => _prefs.getBool(_autoSyncKey) ?? true;
  Future<void> setAutoSync(bool value) => _prefs.setBool(_autoSyncKey, value);

  bool get captureEnabled => _prefs.getBool(_captureKey) ?? true;
  Future<void> setCaptureEnabled(bool value) =>
      _prefs.setBool(_captureKey, value);

  int get captureIntervalSeconds =>
      _prefs.getInt(_intervalKey) ?? defaultCaptureIntervalSeconds;
  Future<void> setCaptureIntervalSeconds(int value) =>
      _prefs.setInt(_intervalKey, value);

  AppThemeMode get themeMode => switch (_prefs.getString(_themeKey)) {
    'light' => AppThemeMode.light,
    'dark' => AppThemeMode.dark,
    _ => AppThemeMode.system,
  };
  Future<void> setThemeMode(AppThemeMode mode) =>
      _prefs.setString(_themeKey, mode.name);

  bool collectorEnabled(String id, {bool fallback = true}) =>
      _prefs.getBool('$_collectorKey.$id') ?? fallback;
  Future<void> setCollectorEnabled(String id, bool value) =>
      _prefs.setBool('$_collectorKey.$id', value);

  /// Opt-in, privacy-preserving diagnostics. Off by default.
  bool get diagnosticsEnabled => _prefs.getBool(_diagnosticsKey) ?? false;
  Future<void> setDiagnosticsEnabled(bool value) =>
      _prefs.setBool(_diagnosticsKey, value);

  /// In-app wellbeing break reminders. OS notification scheduling is not part
  /// of this build; see the Notifications card in Settings.
  bool get breakRemindersEnabled => _prefs.getBool(_remindersKey) ?? true;
  Future<void> setBreakRemindersEnabled(bool value) =>
      _prefs.setBool(_remindersKey, value);

  /// The one-time permission setup screen is shown after the first successful
  /// device connection. Existing installs see it once after upgrading.
  bool get permissionSetupCompleted =>
      _prefs.getBool(_permissionSetupKey) ?? false;
  Future<void> setPermissionSetupCompleted(bool value) =>
      _prefs.setBool(_permissionSetupKey, value);

  /// Android shows the notification prompt only once. Remember that we asked,
  /// even if the user denied it, so the app never nags on every launch.
  bool get notificationPermissionPrompted =>
      _prefs.getBool(_notificationPromptKey) ?? false;
  Future<void> setNotificationPermissionPrompted(bool value) =>
      _prefs.setBool(_notificationPromptKey, value);

  /// Set when the user chose "Not now" for activity insights. It is cleared
  /// automatically when they turn the collectors back on.
  bool get usageAccessDismissed =>
      _prefs.getBool(_usageAccessDismissedKey) ?? false;
  Future<void> setUsageAccessDismissed(bool value) =>
      _prefs.setBool(_usageAccessDismissedKey, value);

  List<Map<String, dynamic>> diagnosticEvents() {
    final raw = _prefs.getString(_diagnosticEventsKey);
    if (raw == null || raw.isEmpty) return <Map<String, dynamic>>[];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is List) {
        return [
          for (final item in decoded)
            if (item is Map) Map<String, dynamic>.from(item),
        ];
      }
    } on FormatException {
      // Corrupt local diagnostics must never break app startup.
    }
    return <Map<String, dynamic>>[];
  }

  Future<void> recordDiagnostic(Map<String, dynamic> event) async {
    if (!diagnosticsEnabled) return;
    final events = diagnosticEvents();
    events.insert(0, {
      ...event,
      'captured_at': DateTime.now().toUtc().toIso8601String(),
    });
    if (events.length > maxDiagnosticEvents) {
      events.removeRange(maxDiagnosticEvents, events.length);
    }
    await _prefs.setString(_diagnosticEventsKey, jsonEncode(events));
  }

  Future<void> clearDiagnosticHistory() => _prefs.remove(_diagnosticEventsKey);
}
