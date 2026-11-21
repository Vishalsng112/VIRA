import 'package:flutter/foundation.dart';
import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/layout.dart';
import '../../app/widgets.dart';
import '../../core/config/app_config.dart';
import '../../services/notifications/notification_hub.dart';

/// One-time setup shown after the first successful connection.
///
/// Notifications are a normal Android runtime permission and can be requested
/// in-app. Usage Access is a special app access: Android only lets the user
/// grant it in system settings, so this screen explains it once and then gets
/// out of the way. Nothing is enabled unless the user opts in.
class PermissionSetupPage extends StatefulWidget {
  const PermissionSetupPage({super.key});

  @override
  State<PermissionSetupPage> createState() => _PermissionSetupPageState();
}

class _PermissionSetupPageState extends State<PermissionSetupPage>
    with WidgetsBindingObserver {
  AppController? _controller;
  bool _notifications = false;
  bool _usageAccess = false;
  bool _sideloaded = false;
  bool _busy = false;
  bool _wantInsights = false;
  bool _notificationPrompted = false;

  bool get _isAndroid =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _initialize());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _refreshUsageAccess();
    }
  }

  Future<void> _initialize() async {
    final controller = AppScope.of(context, listen: false);
    _controller = controller;
    final usageAccess = await controller.hasUsageAccess();
    if (!mounted) return;
    setState(() {
      _usageAccess = usageAccess;
      _sideloaded = controller.isSideloaded;
    });

    if (!controller.settings.notificationPermissionPrompted &&
        !_notificationPrompted) {
      _notificationPrompted = true;
      await controller.settings.setNotificationPermissionPrompted(true);
      final granted = await NotificationHub.instance.requestPermission(
        controller: controller,
      );
      if (mounted) setState(() => _notifications = granted);
    }
  }

  Future<void> _requestNotifications() async {
    final controller = _controller;
    if (controller == null) return;
    setState(() => _busy = true);
    final granted = await NotificationHub.instance.requestPermission(
      controller: controller,
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      _notifications = granted;
    });
  }

  Future<void> _openUsageSettings() async {
    final controller = _controller;
    if (controller == null) return;
    setState(() {
      _busy = true;
      _wantInsights = true;
    });
    final opened = await controller.requestCollectorAccess(collectorAppUsage);
    if (!mounted) return;
    setState(() => _busy = false);
    if (!opened) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Android did not open the Usage Access settings page.'),
        ),
      );
    }
  }

  Future<void> _refreshUsageAccess() async {
    final controller = _controller;
    if (controller == null) return;
    final usageAccess = await controller.hasUsageAccess();
    if (!mounted) return;
    if (usageAccess != _usageAccess) {
      setState(() => _usageAccess = usageAccess);
    }
    if (usageAccess && _wantInsights) {
      await controller.setActivityInsightsEnabled(true);
      if (mounted) setState(() => _wantInsights = false);
    }
  }

  Future<void> _finish({required bool enableInsights}) async {
    final controller = _controller;
    if (controller == null) return;
    setState(() => _busy = true);
    await _refreshUsageAccess();
    await controller.completePermissionSetup(
      enableActivityInsights: enableInsights && _usageAccess,
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: ViraLayout.pageInsets(context),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 680),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      const BrandMark(size: 48),
                      const SizedBox(width: 14),
                      Text(
                        'VIRA Link',
                        style: theme.textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          letterSpacing: -0.4,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 24),
                  Text(
                    'Set up your device',
                    style: theme.textTheme.headlineMedium?.copyWith(
                      fontWeight: FontWeight.w700,
                      letterSpacing: -0.8,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    _isAndroid
                        ? 'Two optional permissions make VIRA Link more useful. '
                              'You can change both later in Settings.'
                        : 'Notifications are optional and can be changed later '
                              'in Settings.',
                    style: theme.textTheme.bodyLarge?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                      height: 1.45,
                    ),
                  ),
                  const SizedBox(height: 20),
                  _notificationCard(theme),
                  if (_isAndroid) ...[
                    const SizedBox(height: 14),
                    _usageAccessCard(theme),
                  ],
                  const SizedBox(height: 20),
                  FilledButton(
                    onPressed: _busy
                        ? null
                        : () => _finish(enableInsights: _wantInsights),
                    child: const Text('Continue'),
                  ),
                  const SizedBox(height: 4),
                  TextButton(
                    onPressed: _busy
                        ? null
                        : () => _finish(enableInsights: false),
                    child: const Text('Not now'),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'VIRA Link only captures the signals you turn on. '
                    'Nothing is uploaded until you connect it to your server.',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _notificationCard(ThemeData theme) => SectionCard(
    leading: const Icon(Icons.notifications_active_outlined),
    title: 'Notifications',
    subtitle: 'Agent results and break reminders while VIRA Link is running.',
    trailing: StatusPill(
      label: _notifications ? 'Allowed' : 'Not enabled',
      tone: _notifications ? StatusTone.success : StatusTone.neutral,
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          _notifications
              ? 'Notifications are enabled for VIRA Link.'
              : _isAndroid
              ? 'Android will show the standard Allow / Don’t allow prompt.'
              : 'Your browser or operating system will ask for permission.',
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
            height: 1.4,
          ),
        ),
        if (!_notifications) ...[
          const SizedBox(height: 10),
          FilledButton.tonalIcon(
            onPressed: _busy ? null : _requestNotifications,
            icon: const Icon(Icons.notifications_none_rounded, size: 18),
            label: const Text('Allow notifications'),
          ),
        ],
      ],
    ),
  );

  Widget _usageAccessCard(ThemeData theme) => SectionCard(
    leading: const Icon(Icons.insights_outlined),
    title: 'Activity insights',
    subtitle:
        'App usage and screen time. Optional, and off unless you enable it.',
    trailing: StatusPill(
      label: _usageAccess ? 'Allowed' : 'Optional',
      tone: _usageAccess ? StatusTone.success : StatusTone.neutral,
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Android requires Usage Access for app usage and screen-time reports. '
          'The app cannot grant this itself; Android opens its settings page so '
          'you can decide.',
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
            height: 1.4,
          ),
        ),
        if (_sideloaded && !_usageAccess) ...[
          const SizedBox(height: 10),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: theme.colorScheme.tertiaryContainer,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Text(
              'If the Usage Access switch is greyed out, Android is blocking '
              'apps installed outside the Play Store. Open App info → ⋮ → '
              'Allow restricted settings, then return here.',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onTertiaryContainer,
                height: 1.4,
              ),
            ),
          ),
        ],
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: _busy ? null : _openUsageSettings,
          icon: const Icon(Icons.open_in_new_rounded, size: 18),
          label: Text(
            _usageAccess
                ? 'Manage in Android settings'
                : 'Enable activity insights',
          ),
        ),
      ],
    ),
  );
}
