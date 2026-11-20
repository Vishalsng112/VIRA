import 'dart:async';

import '../../core/config/app_config.dart';
import '../../core/models/captured_event.dart';
import '../../data/storage/outbox_store.dart';
import '../../data/storage/settings_store.dart';
import 'collector.dart';
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
    this.onChanged,
  }) : _collectors = [
         DeviceStatusCollector(),
         HardwareCollector(),
         NetworkCollector(),
       ];

  final OutboxStore outbox;
  final SettingsStore settings;
  final PlatformProbe probe;
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

  List<String> get capabilities =>
      _collectors.map((item) => item.capability).toList();

  Map<String, String> get capabilityStatus => {
    for (final entry in _states.entries) entry.key: entry.value.status,
  };

  int get lastEventCount => _states.values.fold(
    0,
    (total, state) => total + state.lastEventCount,
  );

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
          final events = await collector.collect(probe);
          for (final event in events) {
            await outbox.enqueue(event);
          }
          total += events.length;
          _states[collector.id] = current.copyWith(
            status: events.isEmpty ? 'unavailable' : 'available',
            lastRun: DateTime.now().toUtc(),
            lastEventCount: events.length,
            lastError: null,
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
