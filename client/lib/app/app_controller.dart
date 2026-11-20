import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/config/app_config.dart';
import '../core/models/captured_event.dart';
import '../core/models/device_info.dart';
import '../data/api/vira_api.dart';
import '../data/storage/credential_store.dart';
import '../data/storage/outbox_store.dart';
import '../data/storage/settings_store.dart';
import '../services/capture/capture_service.dart';
import '../services/capture/platform_probe.dart';
import '../services/sync/sync_service.dart';

enum AppConnectionState { starting, disconnected, connecting, connected, error }

class AppController extends ChangeNotifier {
  AppController._({
    required this.settings,
    required this.credentials,
    required this.outbox,
    required this.probe,
  });

  final SettingsStore settings;
  final CredentialStore credentials;
  final OutboxStore outbox;
  final PlatformProbe probe;

  AppConnectionState _state = AppConnectionState.starting;
  StoredCredentials _stored = const StoredCredentials();
  DeviceProfile? _profile;
  ViraApi? _api;
  CaptureService? _capture;
  SyncService? _sync;
  DeviceInfo? _currentDevice;
  List<DeviceInfo> _devices = const [];
  String? _error;
  String? _devicesError;
  bool _busy = false;
  int _pendingCount = 0;

  static Future<AppController> create() async {
    final controller = AppController._(
      settings: await SettingsStore.open(),
      credentials: CredentialStore(),
      outbox: await OutboxStore.open(),
      probe: createPlatformProbe(),
    );
    await controller._boot();
    return controller;
  }

  AppConnectionState get state => _state;
  String get serverUrl => _stored.serverUrl ?? settings.serverUrl;
  String? get username => _stored.username;
  String? get deviceId => _stored.deviceId;
  DeviceProfile? get profile => _profile;
  DeviceInfo? get currentDevice => _currentDevice;
  List<DeviceInfo> get devices => _devices;
  String? get error => _error;
  String? get devicesError => _devicesError;
  bool get busy => _busy;
  int get pendingCount => _pendingCount;
  bool get isConnected => _state == AppConnectionState.connected;

  SyncSnapshot get syncSnapshot =>
      _sync?.snapshot.value ?? const SyncSnapshot();

  List<CollectorState> get collectors => _capture?.states ?? const [];

  bool get captureEnabled => _capture?.captureEnabled ?? settings.captureEnabled;
  bool get autoSync => settings.autoSync;

  String get suggestedDeviceName {
    final profile = _profile;
    if (profile == null) return 'My device';
    final host = profile.hostname.trim();
    if (host.isNotEmpty && host != 'browser' && host != 'localhost') {
      return host;
    }
    return '${_titleCase(profile.platform)} ${profile.deviceType}';
  }

  Future<void> _boot() async {
    try {
      _profile = await probe.profile();
      _stored = await credentials.load();
      _pendingCount = await outbox.depth();
      if (_stored.hasDevice) {
        _api = _buildApi(_stored);
        await _startServices();
        _state = AppConnectionState.connected;
        unawaited(refreshDevices());
      } else {
        _state = AppConnectionState.disconnected;
      }
    } on Object catch (error) {
      _state = AppConnectionState.disconnected;
      _error = error.toString();
    }
    notifyListeners();
  }

  ViraApi _buildApi(StoredCredentials stored) => ViraApi(
    stored.serverUrl ?? settings.serverUrl,
    clientVersion: appVersion,
  )
    ..sessionId = stored.sessionId
    ..deviceId = stored.deviceId
    ..deviceToken = stored.deviceToken;

  Future<void> _startServices() async {
    final api = _api;
    if (api == null) return;
    if (_capture == null) {
      _capture = CaptureService(
        outbox: outbox,
        settings: settings,
        probe: probe,
        onChanged: _onLocalDataChanged,
      );
      await _capture!.start();
    }
    if (_sync == null) {
      _sync = SyncService(
        api: api,
        outbox: outbox,
        capture: _capture!,
        probe: probe,
        onChanged: _onSyncChanged,
      );
      _sync!.snapshot.addListener(_onSyncChanged);
      await _sync!.start(autoSync: () => settings.autoSync);
    }
  }

  Future<void> connect({
    required String server,
    required String username,
    required String password,
    required String deviceName,
  }) async {
    if (_busy) return;
    _busy = true;
    _state = AppConnectionState.connecting;
    _error = null;
    notifyListeners();
    try {
      final normalized = ViraApi.normalizeBaseUrl(server);
      final api = ViraApi(normalized, clientVersion: appVersion);
      await api.login(username, password);
      final profile = _profile ?? await probe.profile();
      final name = deviceName.trim().isEmpty
          ? suggestedDeviceName
          : deviceName.trim();
      final capabilities =
          _capture?.capabilities ??
          const [collectorDeviceStatus, collectorHardware, collectorNetwork];
      final (device, token) = await api.registerDevice(
        displayName: name,
        profile: profile,
        capabilities: capabilities,
      );
      final session = api.sessionId;
      if (session == null) {
        throw ViraApiException(
          401,
          'no_session',
          'The server did not return a session.',
        );
      }
      await credentials.save(
        serverUrl: normalized,
        username: username.trim(),
        sessionId: session,
        deviceId: device.deviceId,
        deviceToken: token,
      );
      await settings.setServerUrl(normalized);
      await settings.setDeviceName(name);
      _stored = StoredCredentials(
        serverUrl: normalized,
        username: username.trim(),
        sessionId: session,
        deviceId: device.deviceId,
        deviceToken: token,
      );
      _api = api;
      _currentDevice = device;
      await _startServices();
      _state = AppConnectionState.connected;
      unawaited(refreshDevices());
      unawaited(syncNow());
    } on ViraApiException catch (error) {
      _state = AppConnectionState.disconnected;
      _error = error.message;
    } on Object catch (error) {
      _state = AppConnectionState.disconnected;
      _error = error.toString();
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  Future<String?> refreshSession({
    required String username,
    required String password,
  }) async {
    final api = _api;
    final server = _stored.serverUrl;
    final deviceId = _stored.deviceId;
    final deviceToken = _stored.deviceToken;
    if (api == null || server == null || deviceId == null || deviceToken == null) {
      return 'This device is not connected.';
    }
    try {
      await api.login(username, password);
      final session = api.sessionId;
      if (session == null) return 'The server did not return a session.';
      await credentials.save(
        serverUrl: server,
        username: username.trim(),
        sessionId: session,
        deviceId: deviceId,
        deviceToken: deviceToken,
      );
      _stored = StoredCredentials(
        serverUrl: server,
        username: username.trim(),
        sessionId: session,
        deviceId: deviceId,
        deviceToken: deviceToken,
      );
      await refreshDevices();
      notifyListeners();
      return null;
    } on ViraApiException catch (error) {
      return error.message;
    }
  }

  Future<String> setupServer({
    required String server,
    required String username,
    required String password,
    required String confirmation,
  }) async {
    final api = ViraApi(
      ViraApi.normalizeBaseUrl(server),
      clientVersion: appVersion,
    );
    try {
      final result = await api.setupAdministrator(
        username,
        password,
        confirmation,
      );
      return result['recovery_code']?.toString() ?? 'Not returned';
    } finally {
      api.close();
    }
  }

  Future<void> retryConnection() async {
    if (_api == null || !_stored.hasDevice) {
      _state = AppConnectionState.disconnected;
      notifyListeners();
      return;
    }
    _state = AppConnectionState.connected;
    await _startServices();
    await syncNow();
    notifyListeners();
  }

  Future<void> syncNow() async {
    await _sync?.syncNow(forceHeartbeat: true);
    _pendingCount = await outbox.depth();
    notifyListeners();
  }

  Future<void> captureNow() async {
    await _capture?.captureNow();
    _pendingCount = await outbox.depth();
    notifyListeners();
  }

  Future<void> sendTestEvent() async {
    await _capture?.sendTestEvent();
    _pendingCount = await outbox.depth();
    notifyListeners();
  }

  Future<void> setCaptureEnabled(bool value) async {
    await _capture?.setCaptureEnabled(value);
    notifyListeners();
  }

  Future<void> setCollectorEnabled(String id, bool value) async {
    await _capture?.setEnabled(id, value);
    _pendingCount = await outbox.depth();
    notifyListeners();
  }

  Future<void> setAutoSync(bool value) async {
    await settings.setAutoSync(value);
    if (value) unawaited(syncNow());
    notifyListeners();
  }

  Future<void> refreshDevices() async {
    final api = _api;
    if (api == null) return;
    try {
      final devices = await api.devices();
      _devices = devices;
      DeviceInfo? mine;
      for (final device in devices) {
        if (device.deviceId == _stored.deviceId) {
          mine = device;
          break;
        }
      }
      _currentDevice = mine;
      _devicesError = null;
    } on ViraApiException catch (error) {
      _devicesError = error.isAuthFailure
          ? 'Your account session expired. Sign in again to manage devices.'
          : error.message;
    } on Object catch (error) {
      _devicesError = error.toString();
    }
    notifyListeners();
  }

  Future<String?> renameDevice(String id, String name) async {
    final api = _api;
    if (api == null) return 'Not connected';
    final trimmed = name.trim();
    if (trimmed.isEmpty) return 'Device name is required';
    try {
      await api.renameDevice(id, trimmed);
      if (id == _stored.deviceId) await settings.setDeviceName(trimmed);
      await refreshDevices();
      return null;
    } on ViraApiException catch (error) {
      return error.message;
    }
  }

  Future<String?> revokeDevice(String id) async {
    final api = _api;
    if (api == null) return 'Not connected';
    try {
      await api.revokeDevice(id);
      if (id == _stored.deviceId) {
        await _stopServices();
        await credentials.clear();
        await outbox.clearAll();
        _stored = const StoredCredentials();
        _api = null;
        _currentDevice = null;
        _devices = const [];
        _pendingCount = 0;
        _state = AppConnectionState.disconnected;
      } else {
        await refreshDevices();
      }
      notifyListeners();
      return null;
    } on ViraApiException catch (error) {
      return error.message;
    }
  }

  Future<void> disconnect({bool unlink = false}) async {
    final api = _api;
    final id = _stored.deviceId;
    _busy = true;
    notifyListeners();
    try {
      if (unlink && api != null && id != null) {
        try {
          await api.revokeDevice(id);
        } on ViraApiException {
          // Offline unlink: the local credential is still removed below.
        }
      }
      await api?.logout();
      await _stopServices();
      await credentials.clear();
      if (unlink) await outbox.clearAll();
      _stored = const StoredCredentials();
      _api = null;
      _currentDevice = null;
      _devices = const [];
      _pendingCount = await outbox.depth();
      _state = AppConnectionState.disconnected;
      _error = null;
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  Future<void> _stopServices() async {
    _sync?.snapshot.removeListener(_onSyncChanged);
    _sync?.dispose();
    _sync = null;
    await _capture?.stop();
    _capture = null;
    _api?.close();
  }

  Future<List<CapturedEvent>> pendingEvents({int limit = 100}) =>
      outbox.pending(limit: limit);

  Future<List<CapturedEvent>> historyEvents() => outbox.history();

  Future<void> clearHistory() async {
    await outbox.clearHistory();
    notifyListeners();
  }

  void _onLocalDataChanged() {
    unawaited(_refreshPending());
  }

  Future<void> _refreshPending() async {
    _pendingCount = await outbox.depth();
    notifyListeners();
  }

  void _onSyncChanged() {
    _pendingCount = _sync?.snapshot.value.pending ?? _pendingCount;
    notifyListeners();
  }

  String _titleCase(String value) =>
      value.isEmpty ? value : value[0].toUpperCase() + value.substring(1);

  @override
  void dispose() {
    _sync?.snapshot.removeListener(_onSyncChanged);
    _sync?.dispose();
    unawaited(_capture?.stop());
    _api?.close();
    super.dispose();
  }
}
