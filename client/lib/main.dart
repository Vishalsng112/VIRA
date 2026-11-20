import 'dart:ui';

import 'package:material_ui/material_ui.dart';

import 'app/app.dart';
import 'app/app_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final controller = await AppController.create();

  // Diagnostics are recorded locally only when the user opts in. They are
  // redacted before storage and never uploaded automatically.
  FlutterError.onError = (details) {
    FlutterError.presentError(details);
    controller.recordDiagnostic(
      'flutter_error',
      details.exceptionAsString(),
      stack: details.stack,
    );
  };
  PlatformDispatcher.instance.onError = (error, stack) {
    controller.recordDiagnostic('uncaught_error', error, stack: stack);
    return true;
  };

  runApp(ViraLinkApp(controller: controller));
}
