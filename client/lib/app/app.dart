import 'package:material_ui/material_ui.dart';

import 'app_controller.dart';
import 'app_scope.dart';
import 'layout.dart';
import 'notification_host.dart';
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
      builder: (context, _) => LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < ViraLayout.compactBreakpoint;
          return MaterialApp(
            title: appName,
            debugShowCheckedModeBanner: false,
            theme: buildLightTheme(compact: compact),
            darkTheme: buildDarkTheme(compact: compact),
            themeMode: switch (widget.controller.themeMode) {
              AppThemeMode.system => ThemeMode.system,
              AppThemeMode.light => ThemeMode.light,
              AppThemeMode.dark => ThemeMode.dark,
            },
            home: AppBackground(
              child: NotificationHost(
                controller: widget.controller,
                child: const AppShell(),
              ),
            ),
          );
        },
      ),
    ),
  );
}
