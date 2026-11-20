class DesktopWindowSample {
  const DesktopWindowSample({
    required this.appId,
    required this.appName,
    required this.title,
    required this.pid,
    required this.method,
  });

  final String appId;
  final String appName;
  final String title;
  final int? pid;
  final String method;

  String get key => appId.isEmpty ? appName : appId;

  Map<String, dynamic> toJson() => {
    'app_id': appId,
    'app_name': appName,
    'title': title,
    if (pid != null) 'pid': pid,
    'method': method,
  };
}

abstract class DesktopWindowProbe {
  Future<DesktopWindowSample?> activeWindow();
}
