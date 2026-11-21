import 'dart:async';

import '../../core/config/app_config.dart';
import '../../core/models/captured_event.dart';
import '../../core/models/device_signals.dart';
import '../../data/storage/outbox_store.dart';
import '../../data/storage/session_ledger.dart';
import '../../data/storage/settings_store.dart';
import '../../data/storage/usage_ledger.dart';
import 'collector.dart';
import 'collectors/active_window_collector.dart';
import 'collectors/app_usage_collector.dart';
import 'collectors/battery_collector.dart';
import 'collectors/device_session_collector.dart';
import 'collectors/health_collector.dart';
import 'collectors/idle_collector.dart';
import 'collectors/device_status_collector.dart';
import 'collectors/hardware_collector.dart';
import 'collectors/network_collector.dart';
import 'platform_probe.dart';

class CollectorState {
  const CollectorState({
    required this.collector,
    required this.enabled,
    this.status = 'unavailable',
    this.lastRun,
    this.lastError,
    this.lastEventCount = 0,
  });

  final Collector collector;
  final bool enabled;
  final String status;
  final DateTime? lastRun;
  final String? lastError;
  final int lastEventCount;

  CollectorState copyWith({
    bool? enabled,
    String? status,
    DateTime? lastRun,
    String? lastError,
    int? lastEventCount,
  }) => CollectorState(
    collector: collector,
    enabled: enabled ?? this.enabled,
    status: status ?? this.status,
    lastRun: lastRun ?? this.lastRun,
    lastError: lastError,
    lastEventCount: lastEventCount ?? this.lastEventCount,
  );
}

class CaptureService {
  CaptureService({
    required this.outbox,
    required this.settings,
    required this.probe,
    required this.usageLedger,
    required this.sessionLedger,
    this.onChanged,
  }) : _collectors = [
         DeviceStatusCollector(),
         HardwareCollector(),
         NetworkCollector(),
         AppUsageCollector(ledger: usageLedger),
         ActiveWindowCollector(ledger: usageLedger),
         DeviceSessionCollector(ledger: sessionLedger),
         BatteryCollector(),
         HealthCollector(),
         IdleCollector(),
       ];

  final OutboxStore outbox;
  final SettingsStore settings;
  final PlatformProbe probe;
  final UsageLedger usageLedger;
  final SessionLedger sessionLedger;
  final void Function()? onChanged;
  final List<Collector> _collectors;

  final Map<String, CollectorState> _states = {};
  final Map<String, DateTime> _nextDue = {};
  Timer? _timer;
  bool _running = false;
  bool _collecting = false;
  bool captureEnabled = true;

  List<CollectorState> get states {
    _ensureStates();
    return _collectors.map((item) => _states[item.id]!).toList();
  }

  List<Collector> get collectors => List.unmodifiable(_collectors);

  bool canRequestAccess(String id) {
    _ensureStates();
    return _states[id]?.collector.canRequestAccess ?? false;
  }

  Future<bool> requestAccess(String id) async {
    _ensureStates();
    final collector = _states[id]?.collector;
    if (collector == null || !collector.canRequestAccess) return false;
    final opened = await collector.requestAccess();
    if (opened) {
      _nextDue[id] = DateTime.now();
      onChanged?.call();
    }
    return opened;
  }

  List<String> get capabilities =>
      _collectors.map((item) => item.capability).toList();

  Map<String, String> get capabilityStatus => {
    for (final entry in _states.entries) entry.key: entry.value.status,
  };

  int get lastEventCount =>
      _states.values.fold(0, (total, state) => total + state.lastEventCount);

  DeviceHealthSnapshot? get health {
    for (final collector in _collectors) {
      if (collector is HealthCollector) return collector.latest;
    }
    return null;
  }

  BatterySnapshot? get battery {
    for (final collector in _collectors) {
      if (collector is BatteryCollector) return collector.latest;
    }
    return null;
  }

  bool collectorHasLocalData(String id) {
    _ensureStates();
    return _states[id]?.collector.hasLocalData ?? false;
  }

  Future<void> clearCollectorData(String id) async {
    _ensureStates();
    final collector = _states[id]?.collector;
    if (collector == null || !collector.hasLocalData) return;
    await collector.clearLocalData();
    onChanged?.call();
  }

  void _ensureStates() {
    for (final collector in _collectors) {
      _states.putIfAbsent(
        collector.id,
        () => CollectorState(
          collector: collector,
          enabled: settings.collectorEnabled(
            collector.id,
            fallback: collector.enabledByDefault,
          ),
        ),
      );
    }
  }

  Future<void> start() async {
    _ensureStates();
    captureEnabled = settings.captureEnabled;
    _running = true;
    _timer?.cancel();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) {
      unawaited(runDue());
    });
    await runDue(force: true);
  }

  Future<void> stop() async {
    _running = false;
    _timer?.cancel();
    _timer = null;
  }

  Future<int> setEnabled(String id, bool enabled) async {
    _ensureStates();
    final state = _states[id];
    if (state == null) return 0;
    await settings.setCollectorEnabled(id, enabled);
    _states[id] = state.copyWith(enabled: enabled);
    if (enabled) _nextDue[id] = DateTime.now();
    onChanged?.call();
    return enabled ? runDue(force: true) : 0;
  }

  Future<bool> hasAccess(String id) async {
    _ensureStates();
    final collector = _states[id]?.collector;
    return await collector?.hasAccess() ?? false;
  }

  /// Enable or disable both collectors that share Android Usage Access.
  Future<void> setActivityInsightsEnabled(bool enabled) async {
    await setEnabled(collectorAppUsage, enabled);
    await setEnabled(collectorScreenSession, enabled);
  }

  Future<void> setCaptureEnabled(bool enabled) async {
    captureEnabled = enabled;
    await settings.setCaptureEnabled(enabled);
    onChanged?.call();
  }

  Future<int> captureNow() => runDue(force: true);

  Future<int> runDue({bool force = false}) async {
    _ensureStates();
    if (!_running || !captureEnabled || _collecting) return 0;
    final now = DateTime.now();
    final due = _collectors.where((collector) {
      if (!(_states[collector.id]?.enabled ?? false)) return false;
      if (force) return true;
      final next = _nextDue[collector.id];
      return next == null || !next.isAfter(now);
    }).toList();
    if (due.isEmpty) return 0;

    _collecting = true;
    var total = 0;
    try {
      for (final collector in due) {
        final current = _states[collector.id]!;
        try {
          final result = await collector.collect(probe);
          for (final event in result.events) {
            await outbox.enqueue(event);
          }
          total += result.events.length;
          _states[collector.id] = current.copyWith(
            status: result.status,
            lastRun: DateTime.now().toUtc(),
            lastEventCount: result.events.length,
            lastError: result.message,
          );
          _nextDue[collector.id] = DateTime.now().add(collector.interval);
        } on Object catch (error) {
          _states[collector.id] = current.copyWith(
            status: 'degraded',
            lastRun: DateTime.now().toUtc(),
            lastEventCount: 0,
            lastError: error.toString(),
          );
          _nextDue[collector.id] = DateTime.now().add(collector.interval);
        }
      }
    } finally {
      _collecting = false;
      if (total > 0) onChanged?.call();
    }
    return total;
  }

  /// A deterministic event used by the "Send test event" action. It follows the
  /// same outbox path as automatic collectors, so it also works offline.
  Future<void> sendTestEvent() async {
    await outbox.enqueue(
      CapturedEvent(
        eventId: _newId(),
        type: 'device.telemetry.test',
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: 'vira_link',
        payload: {
          'app': appName,
          'client_version': appVersion,
          'message': 'Manual test event from VIRA Link',
        },
      ),
    );
    onChanged?.call();
  }

  String _newId() => OutboxStore.newEventId();
}
