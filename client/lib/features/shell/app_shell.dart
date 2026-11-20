import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/modules.dart';
import '../../app/widgets.dart';
import '../onboarding/onboarding_page.dart';
import '../../services/sync/sync_service.dart';

/// Lets any page move the shell to another module (for example,
/// "Ask VIRA" on the overview opens the assistant).
class ShellNavigation extends InheritedWidget {
  const ShellNavigation({
    super.key,
    required this.openModule,
    required super.child,
  });

  final void Function(String moduleId) openModule;

  static ShellNavigation? maybeOf(BuildContext context) =>
      context.getInheritedWidgetOfExactType<ShellNavigation>();

  @override
  bool updateShouldNotify(ShellNavigation oldWidget) => false;
}

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  String _selectedId = 'dashboard';

  static const _bottomOrder = [
    'dashboard',
    'chat',
    'insights',
    'activity',
    'devices',
  ];

  void _open(String id) {
    if (id == _selectedId) return;
    setState(() => _selectedId = id);
  }

  void _openMore(List<AppModule> modules, BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 0, 8, 10),
                child: Text(
                  'More',
                  style: Theme.of(sheetContext).textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
              for (final module in modules)
                ActionTile(
                  icon: module.icon,
                  title: module.label,
                  trailing: _selectedId == module.id
                      ? Icon(
                          Icons.check_circle,
                          color: Theme.of(sheetContext).colorScheme.primary,
                        )
                      : null,
                  onTap: () {
                    Navigator.pop(sheetContext);
                    _open(module.id);
                  },
                ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    if (controller.state != AppConnectionState.connected) {
      return const OnboardingPage();
    }
    final modules = appModulesFor(isAdmin: controller.isAdmin);
    final selected = modules.indexWhere((item) => item.id == _selectedId);
    final selectedIndex = selected < 0 ? 0 : selected;
    final module = modules[selectedIndex];

    return ShellNavigation(
      openModule: _open,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 900;
          if (!wide) return _mobile(controller, modules, module, selectedIndex);
          return _desktop(
            controller,
            modules,
            module,
            selectedIndex,
            constraints,
          );
        },
      ),
    );
  }

  Widget _mobile(
    AppController controller,
    List<AppModule> modules,
    AppModule module,
    int selectedIndex,
  ) {
    final bottom = _bottomModules(modules);
    final bottomIndex = bottom.indexWhere((item) => item.id == module.id);
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _MobileHeader(module: module, controller: controller),
            Expanded(
              child: KeyedSubtree(
                key: ValueKey(module.id),
                child: module.builder(context),
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.fromLTRB(14, 0, 14, 12),
        child: GlassBar(
          radius: 28,
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
          child: NavigationBar(
            selectedIndex: bottomIndex < 0 ? bottom.length : bottomIndex,
            height: 64,
            onDestinationSelected: (index) {
              if (index >= bottom.length) {
                _openMore(modules, context);
                return;
              }
              _open(bottom[index].id);
            },
            destinations: [
              for (final item in bottom)
                NavigationDestination(
                  icon: Icon(item.icon, size: 23),
                  selectedIcon: Icon(item.selectedIcon, size: 23),
                  label: item.label,
                ),
              const NavigationDestination(
                icon: Icon(Icons.grid_view_rounded, size: 23),
                selectedIcon: Icon(Icons.grid_view_rounded, size: 23),
                label: 'More',
              ),
            ],
          ),
        ),
      ),
    );
  }

  List<AppModule> _bottomModules(List<AppModule> modules) {
    final byId = {for (final module in modules) module.id: module};
    final items = [
      for (final id in _bottomOrder)
        if (byId[id] != null) byId[id]!,
    ];
    // Keep 5 slots for the tabs plus one "More" tab.
    if (items.length <= 5) return items;
    return items.take(5).toList();
  }

  Widget _desktop(
    AppController controller,
    List<AppModule> modules,
    AppModule module,
    int selectedIndex,
    BoxConstraints constraints,
  ) {
    final extended = constraints.maxWidth >= 1240;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
          child: Row(
            children: [
              SizedBox(
                width: extended ? 244 : 94,
                child: GlassBar(
                  radius: 28,
                  padding: const EdgeInsets.symmetric(
                    vertical: 14,
                    horizontal: 8,
                  ),
                  child: Column(
                    children: [
                      Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        child: Row(
                          mainAxisAlignment: extended
                              ? MainAxisAlignment.start
                              : MainAxisAlignment.center,
                          children: [
                            const BrandMark(size: 38),
                            if (extended) ...[
                              const SizedBox(width: 12),
                              Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'VIRA Link',
                                    style: Theme.of(context)
                                        .textTheme
                                        .titleMedium
                                        ?.copyWith(
                                          fontWeight: FontWeight.w800,
                                          letterSpacing: -0.4,
                                        ),
                                  ),
                                  Text(
                                    'Device companion',
                                    style: Theme.of(context)
                                        .textTheme
                                        .labelSmall
                                        ?.copyWith(
                                          color: Theme.of(context)
                                              .colorScheme
                                              .onSurfaceVariant,
                                        ),
                                  ),
                                ],
                              ),
                            ],
                          ],
                        ),
                      ),
                      const SizedBox(height: 16),
                      Expanded(
                        child: NavigationRail(
                          extended: extended,
                          labelType: extended
                              ? NavigationRailLabelType.none
                              : NavigationRailLabelType.all,
                          selectedIndex: selectedIndex,
                          onDestinationSelected: (index) =>
                              _open(modules[index].id),
                          groupAlignment: -0.92,
                          destinations: [
                            for (final item in modules)
                              NavigationRailDestination(
                                icon: Icon(item.icon),
                                selectedIcon: Icon(item.selectedIcon),
                                label: Text(item.label),
                              ),
                          ],
                        ),
                      ),
                      const _RailFooter(),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  children: [
                    _WideHeader(module: module, controller: controller),
                    const SizedBox(height: 10),
                    Expanded(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(28),
                        child: KeyedSubtree(
                          key: ValueKey(module.id),
                          child: module.builder(context),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RailFooter extends StatelessWidget {
  const _RailFooter();

  @override
  Widget build(BuildContext context) =>
      const Padding(padding: EdgeInsets.only(bottom: 6), child: BrandFooter());
}

class BrandFooter extends StatelessWidget {
  const BrandFooter({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return PopupMenuButton<String>(
      tooltip: 'About VIRA Link',
      onSelected: (_) {},
      itemBuilder: (context) => const [
        PopupMenuItem(
          enabled: false,
          child: Text('VIRA Link 1.0.0 · private by design'),
        ),
      ],
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: theme.colorScheme.surfaceContainerHighest.withValues(
            alpha: 0.5,
          ),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Icon(
          Icons.verified_user_outlined,
          size: 18,
          color: theme.colorScheme.onSurfaceVariant,
        ),
      ),
    );
  }
}

class _MobileHeader extends StatelessWidget {
  const _MobileHeader({required this.module, required this.controller});

  final AppModule module;
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 12, 14, 6),
      child: Row(
        children: [
          const BrandMark(size: 34),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  module.label,
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.3,
                  ),
                ),
                Text(
                  _syncLabel(controller: controller),
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          _SyncButton(controller: controller),
        ],
      ),
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
    return GlassBar(
      radius: 22,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  module.label,
                  style: theme.textTheme.titleLarge?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: -0.5,
                  ),
                ),
                Text(
                  _syncLabel(controller: controller),
                  style: theme.textTheme.labelSmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          _SyncStatus(controller: controller),
          const SizedBox(width: 8),
          _SyncButton(controller: controller),
        ],
      ),
    );
  }
}

String _syncLabel({required AppController controller}) {
  final snapshot = controller.syncSnapshot;
  return switch (snapshot.state) {
    SyncState.idle => 'Connected · last sync ${_timeAgo(snapshot.lastSync)}',
    SyncState.syncing => 'Syncing your data…',
    SyncState.offline => 'Offline · your data is saved on this device',
    SyncState.error => 'Connection issue · we will retry automatically',
    SyncState.revoked => 'Device access was revoked',
  };
}

String _timeAgo(DateTime? time) {
  if (time == null) return 'just now';
  final diff = DateTime.now().difference(time.toLocal());
  if (diff.inSeconds < 45) return 'just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
  if (diff.inHours < 24) return '${diff.inHours} h ago';
  return '${diff.inDays} d ago';
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
                SyncState.offline =>
                  'Offline. Events stay queued on this device.',
                SyncState.revoked =>
                  'Device access was revoked. Re-enroll this device.',
                SyncState.error => snapshot.lastError ?? 'Sync failed.',
                SyncState.syncing => 'Syncing…',
              };
              ScaffoldMessenger.of(context)
                  .showSnackBar(SnackBar(content: Text(message)));
            },
      icon: syncing
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.sync_rounded),
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
      SyncState.error => ('Retrying', StatusTone.error, Icons.error_outline),
      SyncState.revoked => ('Revoked', StatusTone.error, Icons.block),
    };
    return StatusPill(label: label, tone: tone, icon: icon);
  }
}
