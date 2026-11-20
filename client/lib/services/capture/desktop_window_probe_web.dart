import 'desktop_window_probe_base.dart';

class DesktopWindowProbeWeb implements DesktopWindowProbe {
  @override
  Future<DesktopWindowSample?> activeWindow() async => null;
}

DesktopWindowProbe createDesktopWindowProbe() => DesktopWindowProbeWeb();
