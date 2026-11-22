import 'package:flutter/foundation.dart';

import '../../../core/config/app_config.dart';
import '../../../core/models/captured_event.dart';
import '../../../core/utils/ids.dart';
import '../android_usage_bridge.dart';
import '../collector.dart';
import '../desktop_idle_probe.dart';
import '../platform_probe_base.dart';

/// Focus / idle state on desktop and Android.
///
/// Desktop uses compositor idle time. Android uses UsageStats screen and
/// interaction events, which require Usage Access but no extra service.
class IdleCollector extends Collector {
  IdleCollector({DesktopIdleProbe? probe, SessionSource? sessionSource})
    : probe = probe ?? createDesktopIdleProbe(),
      sessionSource = sessionSource ?? AndroidUsageBridge();

  final DesktopIdleProbe probe;
  final SessionSource sessionSource;
  int? latestSeconds;

  @override
  String get id => collectorIdle;
  @override
  String get title => 'Focus & idle';
  @override
  String get description =>
      'Active, away and idle time. Android needs Usage Access.';
  @override
  String get capability => collectorIdle;
  @override
  String get eventType => 'device.idle.state';
  @override
  String get sourceComponent => 'idle';
  @override
  Duration get interval => const Duration(minutes: 1);
  @override
  bool get enabledByDefault =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.linux ||
          defaultTargetPlatform == TargetPlatform.windows ||
          defaultTargetPlatform == TargetPlatform.macOS);
  @override
  bool get canRequestAccess =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  @override
  Future<bool> hasAccess() async {
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return sessionSource.hasPermission();
    }
    return true;
  }

  @override
  Future<bool> requestAccess() async {
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return sessionSource.openSettings();
    }
    return false;
  }

  @override
  Future<CollectorResult> collect(PlatformProbe probe) async {
    final profile = await probe.profile();
    if (profile.platform == 'android') {
      if (!await sessionSource.hasPermission()) {
        return const CollectorResult.permissionDenied(
          'Grant Usage Access so VIRA Link can read focus and idle state.',
        );
      }
      final sample = await sessionSource.sessionStats(lookback: interval);
      if (sample == null) {
        return const CollectorResult.degraded(
          'Android did not return screen or interaction data.',
        );
      }
      final state = !sample.screenOn
          ? 'idle'
          : sample.interactions > 0
          ? 'active'
          : 'away';
      final idleSeconds = sample.screenOn ? 0 : sample.windowSeconds;
      latestSeconds = idleSeconds;
      return CollectorResult.available([
        CapturedEvent(
          eventId: newUuidV4(),
          type: eventType,
          occurredAt: DateTime.now().toUtc(),
          sourceComponent: sourceComponent,
          payload: {
            'app': appName,
            'client_version': appVersion,
            'platform': 'android',
            'idle_seconds': idleSeconds,
            'state': state,
            'screen_on': sample.screenOn,
            'interactions': sample.interactions,
            'window_seconds': sample.windowSeconds,
          },
        ),
      ]);
    }
    if (!['linux', 'windows', 'macos'].contains(profile.platform)) {
      return const CollectorResult.unavailable(
        'Idle tracking is available on desktop and Android.',
      );
    }
    final seconds = await this.probe.idleSeconds();
    latestSeconds = seconds;
    if (seconds == null) {
      return const CollectorResult.unavailable(
        'No idle API is available on this desktop session.',
      );
    }
    final state = seconds < 60
        ? 'active'
        : seconds < 300
        ? 'away'
        : 'idle';
    return CollectorResult.available([
      CapturedEvent(
        eventId: newUuidV4(),
        type: eventType,
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: sourceComponent,
        payload: {
          'app': appName,
          'client_version': appVersion,
          'idle_seconds': seconds,
          'state': state,
        },
      ),
    ]);
  }
}
