import 'package:material_ui/material_ui.dart';

import 'app_controller.dart';
import 'app_scope.dart';
import 'theme.dart';
import 'widgets.dart';
import '../core/config/app_config.dart';
import '../features/shell/app_shell.dart';

class ViraLinkApp extends StatefulWidget {
  const ViraLinkApp({super.key, required this.controller});

  final AppController controller;

  @override
  State<ViraLinkApp> createState() => _ViraLinkAppState();
}

class _ViraLinkAppState extends State<ViraLinkApp> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.controller.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      widget.controller.onAppResumed();
    }
  }

  @override
  Widget build(BuildContext context) => AppScope(
    controller: widget.controller,
    child: AnimatedBuilder(
      animation: widget.controller,
      builder: (context, _) => MaterialApp(
        title: appName,
        debugShowCheckedModeBanner: false,
        theme: buildLightTheme(),
        darkTheme: buildDarkTheme(),
        themeMode: switch (widget.controller.themeMode) {
          AppThemeMode.system => ThemeMode.system,
          AppThemeMode.light => ThemeMode.light,
          AppThemeMode.dark => ThemeMode.dark,
        },
        home: const AppBackground(child: AppShell()),
      ),
    ),
  );
}
