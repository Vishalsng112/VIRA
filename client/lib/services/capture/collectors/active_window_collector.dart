import 'package:flutter/foundation.dart';

import '../../../core/catalog/app_catalog.dart';
import '../../../core/config/app_config.dart';
import '../../../core/models/app_usage.dart';
import '../../../data/storage/usage_ledger.dart';
import '../collector.dart';
import '../desktop_window_probe.dart';
import '../platform_probe_base.dart';
import '../usage_events.dart';

/// Desktop foreground window usage.
///
/// Samples the active window once a minute, records local durations, and emits
/// an aggregated app-usage event every [emitEvery] (5 minutes by default).
class ActiveWindowCollector extends Collector {
  ActiveWindowCollector({
    required this.ledger,
    DesktopWindowProbe? probe,
    DateTime Function()? clock,
    this.emitEvery = const Duration(minutes: 5),
  }) : probe = probe ?? createDesktopWindowProbe(),
       _clock = clock ?? DateTime.now;

  final UsageLedger ledger;
  final DesktopWindowProbe probe;
  final Duration emitEvery;
  final DateTime Function() _clock;

  final Map<String, int> _pendingMs = {};
  final Map<String, AppUsageSample> _pendingSamples = {};
  DesktopWindowSample? _lastSample;
  DateTime? _lastSampleAt;
  DateTime? _lastEmit;

  @override
  String get id => collectorActiveWindow;
  @override
  String get title => 'Active window';
  @override
  String get description =>
      'Desktop app time across X11, Wayland, Windows and macOS.';
  @override
  String get capability => collectorActiveWindow;
  @override
  String get eventType => 'device.app.usage';
  @override
  String get sourceComponent => 'active_window';
  @override
  Duration get interval => const Duration(minutes: 1);
  @override
  bool get enabledByDefault =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.windows ||
          defaultTargetPlatform == TargetPlatform.macOS);
  @override
  bool get hasLocalData => true;

  @override
  Future<void> clearLocalData() async {
    await ledger.clear();
    _pendingMs.clear();
    _pendingSamples.clear();
    _lastSample = null;
    _lastSampleAt = null;
    _lastEmit = null;
  }

  @override
  Future<CollectorResult> collect(PlatformProbe probe) async {
    final window = await this.probe.activeWindow();
    if (window == null) {
      return const CollectorResult.unavailable(
        'No active-window API was found. On GNOME Wayland run client/packaging/gnome-extension/install.sh, then log out and back in. X11, Sway, Hyprland, KDE, Windows and macOS work without it.',
      );
    }
    final now = _clock();
    final previous = _lastSample;
    final previousAt = _lastSampleAt;
    if (previous != null && previousAt != null) {
      final delta = now.difference(previousAt).inMilliseconds;
      if (delta > 0) {
        final category = categoryForApp(previous.key, previous.appName);
        final sample = AppUsageSample(
          packageName: previous.key,
          label: previous.appName,
          foregroundMs: delta,
          category: category,
          lastUsedAt: now.toUtc(),
        );
        _pendingMs[sample.packageName] =
            (_pendingMs[sample.packageName] ?? 0) + delta;
        _pendingSamples[sample.packageName] = sample;
        await ledger.record([sample], at: now);
      }
    }
    _lastSample = window;
    _lastSampleAt = now;

    if (_pendingMs.isEmpty) return const CollectorResult.available([]);
    if (_lastEmit != null && now.difference(_lastEmit!) < emitEvery) {
      return const CollectorResult.available([]);
    }

    final samples = [
      for (final entry in _pendingMs.entries)
        if (_pendingSamples[entry.key] != null)
          _pendingSamples[entry.key]!.copyWith(foregroundMs: entry.value),
    ];
    _pendingMs.clear();
    _pendingSamples.clear();
    _lastEmit = now;
    return CollectorResult.available(
      buildUsageEvents(
        samples: samples,
        windowSeconds: emitEvery.inSeconds,
        captureMethod: 'desktop_active_window',
        platform: defaultTargetPlatform.name,
      ),
    );
  }
}
