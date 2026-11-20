import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../core/config/app_config.dart';
import '../../core/models/captured_event.dart';
import '../../data/api/vira_api.dart';
import '../../data/storage/outbox_store.dart';
import '../capture/capture_service.dart';
import '../capture/platform_probe.dart';

enum SyncState { idle, syncing, offline, error, revoked }

class SyncSnapshot {
  const SyncSnapshot({
    this.state = SyncState.idle,
    this.lastSync,
    this.lastError,
    this.sentTotal = 0,
    this.pending = 0,
    this.nextRetry,
  });

  final SyncState state;
  final DateTime? lastSync;
  final String? lastError;
  final int sentTotal;
  final int pending;
  final DateTime? nextRetry;

  SyncSnapshot copyWith({
    SyncState? state,
    DateTime? lastSync,
    String? lastError,
    int? sentTotal,
    int? pending,
    DateTime? nextRetry,
    bool clearError = false,
    bool clearRetry = false,
  }) => SyncSnapshot(
    state: state ?? this.state,
    lastSync: lastSync ?? this.lastSync,
    lastError: clearError ? null : (lastError ?? this.lastError),
    sentTotal: sentTotal ?? this.sentTotal,
    pending: pending ?? this.pending,
    nextRetry: clearRetry ? null : (nextRetry ?? this.nextRetry),
  );
}

class SyncService {
  SyncService({
    required this.api,
    required this.outbox,
    required this.capture,
    required this.probe,
    this.onChanged,
  });

  final ViraApi api;
  final OutboxStore outbox;
  final CaptureService capture;
  final PlatformProbe probe;
  final void Function()? onChanged;

  final ValueNotifier<SyncSnapshot> snapshot = ValueNotifier(
    const SyncSnapshot(),
  );

  Timer? _timer;
  bool _busy = false;
  DateTime? _lastHeartbeat;
  DateTime? _nextRetry;
  Duration _backoff = const Duration(seconds: 2);
  bool Function() _autoSync = () => true;

  Future<void> start({
    required bool Function() autoSync,
    Duration interval = const Duration(seconds: defaultSyncIntervalSeconds),
  }) async {
    _autoSync = autoSync;
    _timer?.cancel();
    _timer = Timer.periodic(interval, (_) {
      if (_autoSync()) unawaited(syncNow(forceHeartbeat: false));
    });
    await syncNow(forceHeartbeat: true);
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  Future<void> refreshPending() async {
    final pending = await outbox.depth();
    snapshot.value = snapshot.value.copyWith(pending: pending);
    onChanged?.call();
  }

  Future<void> syncNow({bool forceHeartbeat = false}) async {
    if (_busy) return;
    if (!forceHeartbeat &&
        _nextRetry != null &&
        _nextRetry!.isAfter(DateTime.now())) {
      return;
    }
    _busy = true;
    try {
      final pending = await outbox.depth();
      snapshot.value = snapshot.value.copyWith(
        state: SyncState.syncing,
        pending: pending,
        clearError: true,
      );
      onChanged?.call();

      final now = DateTime.now();
      if (forceHeartbeat ||
          _lastHeartbeat == null ||
          now.difference(_lastHeartbeat!) >
              const Duration(seconds: heartbeatIntervalSeconds)) {
        final profile = await probe.profile();
        await api.heartbeat(
          profile: profile,
          capabilities: capture.capabilities,
          capabilityStatus: capture.capabilityStatus,
          queueBacklog: pending,
        );
        _lastHeartbeat = now;
      }

      var sent = 0;
      var settledAny = true;
      while (settledAny) {
        final batch = await outbox.pending(limit: maxBatchSize);
        if (batch.isEmpty) break;
        final result = await api.sendEvents(batch);
        settledAny = result.statuses.isNotEmpty;
        if (!settledAny) break;
        await outbox.settle(result.statuses, errors: result.errors);
        sent += result.statuses.values
            .where((state) => state == EventDeliveryState.sent)
            .length;
        if (batch.length < maxBatchSize) break;
      }

      final depth = await outbox.depth();
      _backoff = const Duration(seconds: 2);
      _nextRetry = null;
      snapshot.value = snapshot.value.copyWith(
        state: SyncState.idle,
        lastSync: DateTime.now().toUtc(),
        sentTotal: snapshot.value.sentTotal + sent,
        pending: depth,
        clearError: true,
        clearRetry: true,
      );
      onChanged?.call();
    } on ViraApiException catch (error) {
      _handleFailure(error);
    } on Object catch (error) {
      _handleFailure(
        ViraApiException(0, 'client_error', error.toString()),
      );
    } finally {
      _busy = false;
    }
  }

  void _handleFailure(ViraApiException error) {
    if (error.isAuthFailure) {
      _timer?.cancel();
      _timer = null;
      snapshot.value = snapshot.value.copyWith(
        state: SyncState.revoked,
        lastError: error.message,
        clearRetry: true,
      );
      onChanged?.call();
      return;
    }
    final retry = DateTime.now().add(_backoff);
    _nextRetry = retry;
    final nextBackoff = _backoff * 2;
    _backoff = nextBackoff > const Duration(minutes: 2)
        ? const Duration(minutes: 2)
        : nextBackoff;
    snapshot.value = snapshot.value.copyWith(
      state: error.isTransport ? SyncState.offline : SyncState.error,
      lastError: error.message,
      nextRetry: retry,
    );
    onChanged?.call();
  }

  void dispose() {
    stop();
    snapshot.dispose();
  }
}
