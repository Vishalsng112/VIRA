import 'package:material_ui/material_ui.dart';

import '../services/notifications/notification_hub.dart';
import 'app_controller.dart';

/// Starts the live notification stream while the app is connected.
class NotificationHost extends StatefulWidget {
  const NotificationHost({
    super.key,
    required this.controller,
    required this.child,
  });

  final AppController controller;
  final Widget child;

  @override
  State<NotificationHost> createState() => _NotificationHostState();
}

class _NotificationHostState extends State<NotificationHost> {
  bool _connected = false;

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_sync);
    _sync();
  }

  @override
  void dispose() {
    widget.controller.removeListener(_sync);
    NotificationHub.instance.stop();
    super.dispose();
  }

  void _sync() {
    if (!mounted) return;
    final connected = widget.controller.isConnected;
    if (connected == _connected) return;
    _connected = connected;
    if (connected) {
      NotificationHub.instance.start(widget.controller);
    } else {
      NotificationHub.instance.stop();
    }
  }

  @override
  Widget build(BuildContext context) => widget.child;
}
