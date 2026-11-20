import 'desktop_idle_probe_base.dart';

DesktopIdleProbe createDesktopIdleProbe() => DesktopIdleProbeWeb();

class DesktopIdleProbeWeb implements DesktopIdleProbe {
  @override
  Future<int?> idleSeconds() async => null;
}
