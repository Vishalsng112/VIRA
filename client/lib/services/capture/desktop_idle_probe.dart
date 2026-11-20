export 'desktop_idle_probe_base.dart';
export 'desktop_idle_probe_io.dart'
    if (dart.library.js_interop) 'desktop_idle_probe_web.dart';
