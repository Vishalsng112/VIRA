import 'package:flutter/foundation.dart';

import '../../../core/config/app_config.dart';
import '../../../core/models/captured_event.dart';
import '../../../core/models/device_signals.dart';
import '../../../core/utils/ids.dart';
import '../android_usage_bridge.dart';
import '../collector.dart';
import '../platform_probe_base.dart';

/// Battery level, charging state, temperature and power source.
class BatteryCollector extends Collector {
  BatteryCollector({BatterySource? source})
    : source = source ?? AndroidUsageBridge();

  final BatterySource source;
  BatterySnapshot? latest;

  @override
  String get id => collectorBattery;
  @override
  String get title => 'Battery';
  @override
  String get description => 'Level, charging state and temperature.';
  @override
  String get capability => collectorBattery;
  @override
  String get eventType => 'device.battery.state';
  @override
  String get sourceComponent => 'battery';
  @override
  Duration get interval => const Duration(minutes: 5);
  @override
  bool get enabledByDefault =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS);

  @override
  Future<CollectorResult> collect(PlatformProbe probe) async {
    final profile = await probe.profile();
    BatterySnapshot? snapshot;
    if (profile.platform == 'android') {
      snapshot = await source.battery();
    } else {
      final raw = await probe.batterySnapshot();
      if (raw != null) snapshot = BatterySnapshot.fromJson(raw);
    }
    latest = snapshot;
    if (snapshot == null) {
      return const CollectorResult.unavailable(
        'Battery data is not available on this platform.',
      );
    }
    return CollectorResult.available([
      CapturedEvent(
        eventId: newUuidV4(),
        type: eventType,
        occurredAt: DateTime.now().toUtc(),
        sourceComponent: sourceComponent,
        payload: {
          'app': appName,
          'client_version': appVersion,
          ...snapshot.toJson(),
        },
      ),
    ]);
  }
}
