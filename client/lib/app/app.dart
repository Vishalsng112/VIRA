import 'package:material_ui/material_ui.dart';

import 'app_controller.dart';
import 'app_scope.dart';
import 'theme.dart';
import '../core/config/app_config.dart';
import '../features/shell/app_shell.dart';

class ViraLinkApp extends StatefulWidget {
  const ViraLinkApp({super.key, required this.controller});

  final AppController controller;

  @override
  State<ViraLinkApp> createState() => _ViraLinkAppState();
}

class _ViraLinkAppState extends State<ViraLinkApp> {
  @override
  void dispose() {
    widget.controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AppScope(
    controller: widget.controller,
    child: MaterialApp(
      title: appName,
      debugShowCheckedModeBanner: false,
      theme: buildLightTheme(),
      darkTheme: buildDarkTheme(),
      themeMode: ThemeMode.system,
      home: const AppShell(),
    ),
  );
}
