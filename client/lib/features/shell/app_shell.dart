import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/modules.dart';
import '../../app/widgets.dart';
import '../onboarding/onboarding_page.dart';
import '../../services/sync/sync_service.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _selected = 0;

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    if (controller.state != AppConnectionState.connected) {
      return const OnboardingPage();
    }
    final module = appModules[_selected.clamp(0, appModules.length - 1)];
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 900;
        if (!wide) {
          return Scaffold(
            appBar: AppBar(
              titleSpacing: 16,
              title: Row(
                children: [
                  const BrandMark(size: 30),
                  const SizedBox(width: 10),
                  Text(module.label),
                ],
              ),
              actions: [_SyncButton(controller: controller)],
            ),
            body: KeyedSubtree(
              key: ValueKey(module.id),
              child: module.builder(context),
            ),
            bottomNavigationBar: NavigationBar(
              selectedIndex: _selected,
              onDestinationSelected: (index) =>
                  setState(() => _selected = index),
              destinations: [
                for (final item in appModules)
                  NavigationDestination(
                    icon: Icon(item.icon),
                    selectedIcon: Icon(item.selectedIcon),
                    label: item.label,
                  ),
              ],
            ),
          );
        }
        final extended = constraints.maxWidth >= 1220;
        return Scaffold(
          body: Row(
            children: [
              NavigationRail(
                extended: extended,
                selectedIndex: _selected,
                onDestinationSelected: (index) =>
                    setState(() => _selected = index),
                leading: Padding(
                  padding: EdgeInsets.fromLTRB(
                    extended ? 20 : 12,
                    20,
                    extended ? 20 : 12,
                    18,
                  ),
                  child: extended
                      ? Row(
                          children: [
                            const BrandMark(size: 34),
                            const SizedBox(width: 12),
                            Text(
                              'VIRA Link',
                              style: Theme.of(context).textTheme.titleMedium
                                  ?.copyWith(fontWeight: FontWeight.w700),
                            ),
                          ],
                        )
                      : const BrandMark(size: 34),
                ),
                destinations: [
                  for (final item in appModules)
                    NavigationRailDestination(
                      icon: Icon(item.icon),
                      selectedIcon: Icon(item.selectedIcon),
                      label: Text(item.label),
                    ),
                ],
              ),
              const VerticalDivider(width: 1),
              Expanded(
                child: Column(
                  children: [
                    _WideHeader(module: module, controller: controller),
                    const Divider(height: 1),
                    Expanded(
                      child: KeyedSubtree(
                        key: ValueKey(module.id),
                        child: module.builder(context),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _WideHeader extends StatelessWidget {
  const _WideHeader({required this.module, required this.controller});

  final AppModule module;
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      height: 68,
      padding: const EdgeInsets.symmetric(horizontal: 24),
      color: theme.colorScheme.surface,
      child: Row(
        children: [
          Text(
            module.label,
            style: theme.textTheme.titleLarge?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
          const Spacer(),
          _SyncStatus(controller: controller),
          const SizedBox(width: 8),
          _SyncButton(controller: controller),
        ],
      ),
    );
  }
}

class _SyncButton extends StatelessWidget {
  const _SyncButton({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final syncing = controller.syncSnapshot.state == SyncState.syncing;
    return IconButton(
      tooltip: 'Sync now',
      onPressed: syncing
          ? null
          : () async {
              await controller.syncNow();
              if (!context.mounted) return;
              final snapshot = controller.syncSnapshot;
              final message = switch (snapshot.state) {
                SyncState.idle =>
                  snapshot.sentTotal > 0
                      ? 'Sync complete.'
                      : 'Everything is up to date.',
                SyncState.offline => 'Offline. Events stay queued on this device.',
                SyncState.revoked =>
                  'Device access was revoked. Re-enroll this device.',
                SyncState.error => snapshot.lastError ?? 'Sync failed.',
                SyncState.syncing => 'Syncing…',
              };
              ScaffoldMessenger.of(
                context,
              ).showSnackBar(SnackBar(content: Text(message)));
            },
      icon: syncing
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.sync),
    );
  }
}

class _SyncStatus extends StatelessWidget {
  const _SyncStatus({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final snapshot = controller.syncSnapshot;
    final (label, tone, icon) = switch (snapshot.state) {
      SyncState.syncing => ('Syncing', StatusTone.info, Icons.sync),
      SyncState.idle => ('Up to date', StatusTone.success, Icons.check_circle),
      SyncState.offline => ('Offline', StatusTone.warning, Icons.cloud_off),
      SyncState.error => ('Sync issue', StatusTone.error, Icons.error_outline),
      SyncState.revoked => ('Revoked', StatusTone.error, Icons.block),
    };
    return StatusPill(label: label, tone: tone, icon: icon);
  }
}
