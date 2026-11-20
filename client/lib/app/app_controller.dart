import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../core/config/app_config.dart';
import '../core/models/app_usage.dart';
import '../core/models/captured_event.dart';
import '../core/models/device_info.dart';
import '../core/models/device_signals.dart';
import '../core/models/focus_session.dart';
import '../data/api/vira_api.dart';
import '../core/utils/ids.dart';
import '../data/storage/credential_store.dart';
import '../data/storage/focus_ledger.dart';
import '../data/storage/outbox_store.dart';
import '../data/storage/session_ledger.dart';
import '../data/storage/settings_store.dart';
import '../data/storage/usage_ledger.dart';
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
    required this.usageLedger,
    required this.sessionLedger,
    required this.focusLedger,
  });

  final SettingsStore settings;
  final CredentialStore credentials;
  final OutboxStore outbox;
  final PlatformProbe probe;
  final UsageLedger usageLedger;
  final SessionLedger sessionLedger;
  final FocusLedger focusLedger;

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
  bool _isAdmin = false;
  bool _pollingCommands = false;
  Timer? _commandTimer;
  int _pendingCount = 0;

  static Future<AppController> create() async {
    final controller = AppController._(
      settings: await SettingsStore.open(),
      credentials: CredentialStore(),
      outbox: await OutboxStore.open(),
      probe: createPlatformProbe(),
      usageLedger: await UsageLedger.open(),
      sessionLedger: await SessionLedger.open(),
      focusLedger: await FocusLedger.open(),
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
  bool get isAdmin => _isAdmin;
  ViraApi? get api => _api;

  SyncSnapshot get syncSnapshot =>
      _sync?.snapshot.value ?? const SyncSnapshot();

  List<CollectorState> get collectors => _capture?.states ?? const [];

  bool get captureEnabled =>
      _capture?.captureEnabled ?? settings.captureEnabled;
  bool get autoSync => settings.autoSync;
  AppThemeMode get themeMode => settings.themeMode;

  Future<void> setThemeMode(AppThemeMode mode) async {
    if (settings.themeMode == mode) return;
    await settings.setThemeMode(mode);
    notifyListeners();
  }

  /// Cycles System → Light → Dark → System for the quick header toggle.
  Future<void> cycleThemeMode() => setThemeMode(switch (settings.themeMode) {
    AppThemeMode.system => AppThemeMode.light,
    AppThemeMode.light => AppThemeMode.dark,
    AppThemeMode.dark => AppThemeMode.system,
  });

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
      await settings.ensureInstallationId();
      _stored = await credentials.load();
      _isAdmin = _stored.isAdmin;
      _pendingCount = await outbox.depth();
      if (_stored.hasDevice) {
        _api = _buildApi(_stored);
        await _startServices();
        _state = AppConnectionState.connected;
        unawaited(refreshDevices());
        unawaited(refreshIdentity().catchError((_) => _isAdmin));
      } else {
        _state = AppConnectionState.disconnected;
      }
    } on Object catch (error) {
      _state = AppConnectionState.disconnected;
      _error = error.toString();
    }
    notifyListeners();
  }

  ViraApi _buildApi(StoredCredentials stored) =>
      ViraApi(stored.serverUrl ?? settings.serverUrl, clientVersion: appVersion)
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
        usageLedger: usageLedger,
        sessionLedger: sessionLedger,
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
      await _sync!.start(
        autoSync: () =>
            settings.autoSync && !(_capture?.battery?.isLow ?? false),
      );
      _commandTimer?.cancel();
      _commandTimer = Timer.periodic(
        const Duration(seconds: 30),
        (_) => unawaited(_pollCommands()),
      );
      unawaited(_pollCommands());
    }
  }

  bool _hasAdminRole(Map<String, dynamic> login) {
    final principal = login['principal'];
    final roles = principal is Map ? principal['roles'] : null;
    return roles is List && roles.contains('admin');
  }

  Future<bool> refreshIdentity() async {
    final api = _api;
    if (api == null || !_stored.hasSession) return _isAdmin;
    try {
      final me = await api.me();
      final roles = me['roles'];
      final isAdmin = roles is List && roles.contains('admin');
      if (isAdmin != _isAdmin) {
        _isAdmin = isAdmin;
        if (_stored.hasDevice) {
          await credentials.save(
            serverUrl: _stored.serverUrl!,
            username: _stored.username ?? '',
            sessionId: _stored.sessionId!,
            deviceId: _stored.deviceId!,
            deviceToken: _stored.deviceToken!,
            isAdmin: isAdmin,
          );
          _stored = StoredCredentials(
            serverUrl: _stored.serverUrl,
            username: _stored.username,
            sessionId: _stored.sessionId,
            deviceId: _stored.deviceId,
            deviceToken: _stored.deviceToken,
            isAdmin: isAdmin,
          );
        }
        notifyListeners();
      }
      return isAdmin;
    } on ViraApiException catch (error) {
      if (error.isAuthFailure && _isAdmin) {
        _isAdmin = false;
        notifyListeners();
      }
      rethrow;
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
      final login = await api.login(username, password);
      final isAdmin = _hasAdminRole(login);
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
        installationId: await settings.ensureInstallationId(),
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
        isAdmin: isAdmin,
      );
      await settings.setServerUrl(normalized);
      await settings.setDeviceName(name);
      _stored = StoredCredentials(
        serverUrl: normalized,
        username: username.trim(),
        sessionId: session,
        deviceId: device.deviceId,
        deviceToken: token,
        isAdmin: isAdmin,
      );
      _api = api;
      _isAdmin = isAdmin;
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
    if (api == null ||
        server == null ||
        deviceId == null ||
        deviceToken == null) {
      return 'This device is not connected.';
    }
    try {
      final login = await api.login(username, password);
      final isAdmin = _hasAdminRole(login);
      final session = api.sessionId;
      if (session == null) return 'The server did not return a session.';
      await credentials.save(
        serverUrl: server,
        username: username.trim(),
        sessionId: session,
        deviceId: deviceId,
        deviceToken: deviceToken,
        isAdmin: isAdmin,
      );
      _stored = StoredCredentials(
        serverUrl: server,
        username: username.trim(),
        sessionId: session,
        deviceId: deviceId,
        deviceToken: deviceToken,
        isAdmin: isAdmin,
      );
      _isAdmin = isAdmin;
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

  Future<bool> requestCollectorAccess(String id) async {
    final opened = await _capture?.requestAccess(id) ?? false;
    notifyListeners();
    return opened;
  }

  Future<void> onAppResumed() async {
    if (!isConnected) return;
    await captureNow();
    unawaited(syncNow());
  }

  Future<UsageDay> usageToday() => usageLedger.today();

  Future<List<UsageDay>> usageRecent({int days = 7}) =>
      usageLedger.recent(days: days);

  Future<void> clearUsageHistory() async {
    await usageLedger.clear();
    notifyListeners();
  }

  BatterySnapshot? get battery => _capture?.battery;

  DeviceHealthSnapshot? get health => _capture?.health;

  Future<SessionDay> sessionToday() => sessionLedger.today();

  Future<List<SessionDay>> sessionRecent({int days = 7}) =>
      sessionLedger.recent(days: days);

  Future<void> clearSessionHistory() async {
    await sessionLedger.clear();
    notifyListeners();
  }

  Future<void> clearLocalHistory() async {
    await usageLedger.clear();
    await sessionLedger.clear();
    await focusLedger.clear();
    notifyListeners();
  }

  Future<FocusSession?> activeFocus() => focusLedger.active();

  Future<List<FocusSession>> recentFocus({int days = 7}) =>
      focusLedger.recent(days: days);

  Future<void> startFocus({String label = 'Focus', int minutes = 25}) async {
    if (await focusLedger.active() != null) return;
    await focusLedger.start(
      FocusSession(
        id: newUuidV4(),
        label: label,
        startedAt: DateTime.now().toUtc(),
        plannedMinutes: minutes,
      ),
    );
    notifyListeners();
  }

  Future<void> stopFocus() async {
    final current = await focusLedger.active();
    if (current == null) return;
    final completed = current.durationMs >= current.plannedMs;
    final session = await focusLedger.stop(markCompleted: completed);
    if (session == null) return;
    await outbox.enqueue(
      CapturedEvent(
        eventId: newUuidV4(),
        type: 'device.focus.session',
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: 'focus_session',
        payload: {
          'app': appName,
          'client_version': appVersion,
          'id': session.id,
          'label': session.label,
          'planned_minutes': session.plannedMinutes,
          'duration_seconds': session.durationMs ~/ 1000,
          'completed': session.completed,
          'started_at': session.startedAt.toIso8601String(),
          if (session.endedAt != null)
            'ended_at': session.endedAt!.toIso8601String(),
        },
      ),
    );
    _pendingCount = await outbox.depth();
    notifyListeners();
    unawaited(syncNow());
  }

  Future<void> clearFocusHistory() async {
    await focusLedger.clear();
    notifyListeners();
  }

  bool collectorHasLocalData(String id) =>
      _capture?.collectorHasLocalData(id) ?? false;

  Future<void> clearCollectorData(String id) async {
    await _capture?.clearCollectorData(id);
    notifyListeners();
  }

  Future<String> exportLocalData() async {
    final pending = await outbox.pending(limit: 1000);
    final history = await outbox.history();
    final usage = await usageLedger.recent(days: 30);
    final sessions = await sessionLedger.recent(days: 30);
    final payload = {
      'exported_at': DateTime.now().toUtc().toIso8601String(),
      'app': appName,
      'client_version': appVersion,
      'protocol_version': protocolVersion,
      'account': {
        'server': serverUrl,
        'username': username,
        'device_id': deviceId,
      },
      'settings': {
        'auto_sync': autoSync,
        'capture_enabled': captureEnabled,
        'device_name': settings.deviceName,
      },
      'collectors': [
        for (final state in collectors)
          {
            'id': state.collector.id,
            'title': state.collector.title,
            'enabled': state.enabled,
            'status': state.status,
            'event_type': state.collector.eventType,
            'last_run': state.lastRun?.toIso8601String(),
          },
      ],
      'app_usage': usage.map((day) => day.toJson()).toList(),
      'sessions': sessions.map((day) => day.toJson()).toList(),
      'outbox': {
        'pending_count': pending.length,
        'history_count': history.length,
        'pending': pending.map((event) => event.toJson()).toList(),
        'history': history.map((event) => event.toJson()).toList(),
      },
    };
    return const JsonEncoder.withIndent('  ').convert(payload);
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
        _isAdmin = false;
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
      _isAdmin = false;
      _state = AppConnectionState.disconnected;
      _error = null;
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  Future<void> _pollCommands() async {
    final api = _api;
    if (_pollingCommands || api == null || !isConnected) return;
    _pollingCommands = true;
    try {
      final commands = await api.pendingCommands();
      for (final command in commands) {
        final id = (command['id'] ?? '').toString();
        final kind = (command['kind'] ?? '').toString();
        final payload = command['payload'] is Map
            ? Map<String, dynamic>.from(command['payload'] as Map)
            : <String, dynamic>{};
        try {
          final result = await _applyCommand(kind, payload);
          await api.completeCommand(id, result: result);
        } on Object catch (error) {
          await api.completeCommand(
            id,
            status: 'failed',
            result: {'error': error.toString()},
          );
        }
      }
    } on ViraApiException {
      // Offline or command endpoint unavailable; retry on the next tick.
    } on Object {
      // Never let remote-control polling affect capture/sync.
    } finally {
      _pollingCommands = false;
    }
  }

  Future<Map<String, dynamic>> _applyCommand(
    String kind,
    Map<String, dynamic> payload,
  ) async {
    switch (kind) {
      case 'capture.pause':
        await _capture?.setCaptureEnabled(false);
        notifyListeners();
        return {'capture_enabled': false};
      case 'capture.resume':
        await _capture?.setCaptureEnabled(true);
        notifyListeners();
        return {'capture_enabled': true};
      case 'config.update':
        if (payload['auto_sync'] is bool) {
          await settings.setAutoSync(payload['auto_sync'] as bool);
        }
        if (payload['capture_enabled'] is bool) {
          await _capture?.setCaptureEnabled(payload['capture_enabled'] as bool);
        }
        notifyListeners();
        return {'applied': true};
      case 'queue.flush':
        unawaited(syncNow());
        return {'queued': true};
      case 'queue.clear':
        await outbox.clearAll();
        _pendingCount = 0;
        notifyListeners();
        return {'cleared': true};
      case 'update.check':
        return {
          'version': appVersion,
          'platform': profile?.platform ?? 'unknown',
        };
      case 'export.request':
        return {'message': 'Start the export from Settings on this device.'};
      case 'consent.update':
        return {'message': 'Consent is enforced by the VIRA server.'};
      default:
        return {'message': 'Unsupported command: $kind'};
    }
  }

  Future<void> _stopServices() async {
    _commandTimer?.cancel();
    _commandTimer = null;
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
