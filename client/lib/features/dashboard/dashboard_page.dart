import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/theme.dart';
import '../../app/widgets.dart';
import '../../data/storage/outbox_store.dart';
import '../shell/app_shell.dart';
import '../../services/capture/capture_service.dart';
import '../../services/sync/sync_service.dart';

/// Plain-language overview for everyone, with technical details tucked away.
class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final snapshot = controller.syncSnapshot;
    final collectors = controller.collectors;
    final active = collectors
        .where((item) => item.enabled && item.status == 'available')
        .length;
    return RefreshIndicator(
      onRefresh: controller.syncNow,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1080),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  PageHeader(
                    eyebrow: 'Overview',
                    title: _greeting(controller),
                    subtitle:
                        'Here is a simple look at your device and what VIRA knows. '
                        'No technical knowledge needed — the details are at the bottom.',
                  ),
                  const SizedBox(height: 18),
                  _Hero(controller: controller, snapshot: snapshot),
                  if (_collectorsNeedingAttention(controller).isNotEmpty) ...[
                    const SizedBox(height: 14),
                    _PermissionsBanner(controller: controller),
                  ],
                  const SizedBox(height: 14),
                  _QuickStats(
                    controller: controller,
                    snapshot: snapshot,
                    active: active,
                    total: collectors.length,
                  ),
                  const SizedBox(height: 14),
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final wide = constraints.maxWidth >= 860;
                      final sharing = _SharingCard(controller: controller);
                      final connection = _ConnectionCard(
                        controller: controller,
                      );
                      if (!wide) {
                        return Column(
                          children: [
                            sharing,
                            const SizedBox(height: 14),
                            connection,
                          ],
                        );
                      }
                      return Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(flex: 3, child: sharing),
                          const SizedBox(width: 14),
                          Expanded(flex: 2, child: connection),
                        ],
                      );
                    },
                  ),
                  const SizedBox(height: 14),
                  const _HowItWorks(),
                  const SizedBox(height: 14),
                  _AdvancedDetails(controller: controller, snapshot: snapshot),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _greeting(AppController controller) {
    final hour = DateTime.now().hour;
    final part = hour < 12
        ? 'Good morning'
        : hour < 17
        ? 'Good afternoon'
        : 'Good evening';
    final name = controller.username;
    if (name == null || name.trim().isEmpty) return part;
    return '$part, ${name[0].toUpperCase()}${name.substring(1)}';
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.controller, required this.snapshot});

  final AppController controller;
  final SyncSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    final (icon, title, message, tone) = switch (snapshot.state) {
      SyncState.revoked => (
        Icons.link_off,
        'This device needs to be linked again',
        'Your server no longer accepts this device. Go to Settings and connect it again.',
        StatusTone.error,
      ),
      SyncState.offline => (
        Icons.cloud_off_rounded,
        'You are offline — everything is still safe',
        'Nothing is lost. New activity is saved on this device and will be sent automatically when you are back online.',
        StatusTone.warning,
      ),
      SyncState.error => (
        Icons.sync_problem_rounded,
        'VIRA is having trouble connecting',
        snapshot.lastError ?? 'Your data is saved on this device. We will keep trying in the background.',
        StatusTone.warning,
      ),
      SyncState.syncing => (
        Icons.sync_rounded,
        'Sending your latest activity',
        'This usually takes a few seconds. You can keep using the app.',
        StatusTone.info,
      ),
      SyncState.idle =>
        controller.pendingCount > 0
            ? (
                Icons.cloud_upload_outlined,
                'A few things are waiting to be sent',
                'Your activity is saved safely on this device and will be sent automatically.',
                StatusTone.info,
              )
            : (
                Icons.verified_rounded,
                'You are all caught up',
                'Your device is connected to ${controller.serverUrl} and everything you chose to share is saved.',
                StatusTone.success,
              ),
    };
    final navigator = ShellNavigation.maybeOf(context);
    return HeroStatus(
      icon: icon,
      title: title,
      message: message,
      tone: tone,
      actions: [
        FilledButton.icon(
          onPressed: () {
            if (navigator != null) {
              navigator.openModule('chat');
            } else {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(content: Text('Open Assistant from the menu.')),
              );
            }
          },
          icon: const Icon(Icons.auto_awesome, size: 18),
          label: const Text('Ask VIRA'),
        ),
        OutlinedButton.icon(
          onPressed: controller.syncNow,
          icon: const Icon(Icons.sync_rounded, size: 18),
          label: const Text('Sync now'),
        ),
      ],
    );
  }
}

List<CollectorState> _collectorsNeedingAttention(AppController controller) {
  return controller.collectors.where((state) {
    if (state.status == 'permission_denied') return true;
    return state.enabled &&
        state.status == 'unavailable' &&
        state.collector.canRequestAccess;
  }).toList();
}

Future<void> _showPermissionSheet(
  BuildContext context,
  AppController controller,
) async {
  await showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (sheetContext) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Permissions and notifications',
              style: Theme.of(
                sheetContext,
              ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 6),
            Text(
              'VIRA Link only captures signals you enable. Some signals also need '
              'an operating-system permission. Nothing is granted automatically.',
              style: Theme.of(sheetContext).textTheme.bodyMedium?.copyWith(
                color: Theme.of(sheetContext).colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 14),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                children: [
                  for (final state in controller.collectors)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: Icon(_permissionIcon(state.status)),
                      title: Text(state.collector.title),
                      subtitle: Text(_permissionExplanation(state)),
                      trailing: state.collector.canRequestAccess
                          ? TextButton(
                              onPressed: () async {
                                await controller.requestCollectorAccess(
                                  state.collector.id,
                                );
                                if (sheetContext.mounted) {
                                  Navigator.pop(sheetContext);
                                }
                              },
                              child: const Text('Allow'),
                            )
                          : null,
                    ),
                  const Divider(),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.notifications_none_rounded),
                    title: const Text('Notifications'),
                    subtitle: const Text(
                      'In-app break reminders are available now. OS notifications '
                      'are not scheduled by this build, so VIRA will not ask for '
                      'notification permission yet.',
                    ),
                    trailing: const StatusPill(
                      label: 'In-app only',
                      tone: StatusTone.info,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 10),
            FilledButton(
              onPressed: () => Navigator.pop(sheetContext),
              child: const Text('Done'),
            ),
          ],
        ),
      ),
    ),
  );
}

IconData _permissionIcon(String status) => switch (status) {
  'available' => Icons.check_circle_outline,
  'permission_denied' => Icons.lock_outline,
  'degraded' => Icons.warning_amber_rounded,
  _ => Icons.info_outline,
};

String _permissionExplanation(CollectorState state) {
  if (state.status == 'permission_denied') {
    return 'Needs an operating-system permission. Tap Allow to open the right settings page.';
  }
  if (state.status == 'available') {
    return state.enabled ? 'Available and shared.' : 'Available but turned off.';
  }
  if (state.status == 'degraded') {
    return state.lastError ?? 'Limited on this platform right now.';
  }
  return state.collector.description;
}

class _PermissionsBanner extends StatelessWidget {
  const _PermissionsBanner({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final pending = _collectorsNeedingAttention(controller);
    final denied = pending.where((s) => s.status == 'permission_denied').length;
    return Card(
      color: theme.colorScheme.tertiaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              Icons.lock_open_rounded,
              color: theme.colorScheme.onTertiaryContainer,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    denied > 0
                        ? 'A couple of signals need your permission'
                        : 'Some signals are limited on this device',
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: theme.colorScheme.onTertiaryContainer,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    '${pending.length} signal${pending.length == 1 ? "" : "s"} '
                    'could work better. Review permissions, or keep them off.',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onTertiaryContainer,
                    ),
                  ),
                  const SizedBox(height: 8),
                  FilledButton.tonalIcon(
                    onPressed: () => _showPermissionSheet(context, controller),
                    icon: const Icon(Icons.tune_rounded, size: 18),
                    label: const Text('Review permissions'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _QuickStats extends StatelessWidget {
  const _QuickStats({
    required this.controller,
    required this.snapshot,
    required this.active,
    required this.total,
  });

  final AppController controller;
  final SyncSnapshot snapshot;
  final int active;
  final int total;

  @override
  Widget build(BuildContext context) {
    final battery = controller.battery;
    final cards = [
      StatCard(
        icon: Icons.shield_moon_outlined,
        label: 'Sharing',
        value: total == 0 ? 'Starting' : '$active of $total',
        caption: total == 0
            ? 'Preparing this device'
            : active == 0
            ? 'Nothing is being shared'
            : 'Kinds of activity enabled',
        accent: const Color(0xFF5B6CFF),
      ),
      StatCard(
        icon: Icons.cloud_done_outlined,
        label: 'Waiting to send',
        value: '${controller.pendingCount}',
        caption: controller.pendingCount == 0
            ? 'Nothing is waiting'
            : 'Saved safely on this device',
        accent: const Color(0xFF4ADE9B),
      ),
      StatCard(
        icon: Icons.schedule_rounded,
        label: 'Last updated',
        value: _shortAgo(snapshot.lastSync),
        caption: snapshot.lastSync == null
            ? 'Not synced yet'
            : OutboxStore.prettyTime(snapshot.lastSync),
        accent: const Color(0xFF9B6BFF),
      ),
      StatCard(
        icon: battery?.charging == true
            ? Icons.battery_charging_full_rounded
            : Icons.battery_std_rounded,
        label: 'Battery',
        value: battery?.levelPercent == null
            ? '—'
            : '${battery!.levelPercent}%',
        caption: battery == null
            ? 'Not available on this device'
            : battery.charging == true
            ? 'Charging'
            : 'On battery',
        accent: const Color(0xFFFFB55C),
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        const spacing = 12.0;
        final columns = constraints.maxWidth >= 900
            ? 4
            : constraints.maxWidth >= 380
            ? 2
            : 1;
        final width =
            (constraints.maxWidth - spacing * (columns - 1)) / columns;
        return Wrap(
          spacing: spacing,
          runSpacing: spacing,
          children: [
            for (final card in cards) SizedBox(width: width, child: card),
          ],
        );
      },
    );
  }

  String _shortAgo(DateTime? time) {
    if (time == null) return '—';
    final diff = DateTime.now().difference(time.toLocal());
    if (diff.inSeconds < 45) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m';
    if (diff.inHours < 24) return '${diff.inHours}h';
    return '${diff.inDays}d';
  }
}

class _SharingCard extends StatelessWidget {
  const _SharingCard({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final collectors = controller.collectors;
    return SectionCard(
      title: 'What this device shares',
      subtitle: 'Turn anything off at any time. VIRA only receives what is switched on here.',
      trailing: FilledButton.tonalIcon(
        onPressed: controller.captureNow,
        icon: const Icon(Icons.refresh_rounded, size: 18),
        label: const Text('Refresh'),
      ),
      child: Column(
        children: [
          for (final state in collectors)
            _SharingRow(
              state: state,
              onChanged: (value) =>
                  controller.setCollectorEnabled(state.collector.id, value),
              onRequestAccess: () =>
                  controller.requestCollectorAccess(state.collector.id),
            ),
          if (collectors.isEmpty)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('Getting this device ready…'),
            ),
        ],
      ),
    );
  }
}

class _SharingRow extends StatelessWidget {
  const _SharingRow({
    required this.state,
    required this.onChanged,
    required this.onRequestAccess,
  });

  final CollectorState state;
  final ValueChanged<bool> onChanged;
  final VoidCallback onRequestAccess;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final meta = _collectorMeta(state.collector.id, state.collector.title);
    final permission = state.status == 'permission_denied';
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: meta.color.withValues(alpha: 0.13),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Icon(meta.icon, size: 20, color: meta.color),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        meta.title,
                        style: theme.textTheme.bodyLarge?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    if (permission) ...[
                      const SizedBox(width: 8),
                      const StatusPill(
                        label: 'Needs access',
                        tone: StatusTone.warning,
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  meta.description,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                    height: 1.4,
                  ),
                ),
                if (permission) ...[
                  const SizedBox(height: 6),
                  TextButton.icon(
                    onPressed: onRequestAccess,
                    icon: const Icon(Icons.lock_open_outlined, size: 17),
                    label: const Text('Allow access'),
                  ),
                ],
              ],
            ),
          ),
          Switch(value: state.enabled, onChanged: onChanged),
        ],
      ),
    );
  }

  _CollectorMeta _collectorMeta(String id, String fallback) => switch (id) {
    'device_status' => const _CollectorMeta(
      Icons.phone_android_rounded,
      'Device status',
      'Basic information like the model and operating system.',
      Color(0xFF5B6CFF),
    ),
    'hardware_state' => const _CollectorMeta(
      Icons.memory_rounded,
      'Device health',
      'Storage, memory and temperature, so VIRA can spot problems.',
      Color(0xFF9B6BFF),
    ),
    'network_state' => const _CollectorMeta(
      Icons.wifi_rounded,
      'Network',
      'Whether you are online and what kind of connection you use.',
      Color(0xFF52D6E8),
    ),
    'app_usage' => const _CollectorMeta(
      Icons.apps_rounded,
      'App usage',
      'Which apps you open and how long you spend in them.',
      Color(0xFFFF7AB6),
    ),
    'screen_session' => const _CollectorMeta(
      Icons.screen_lock_portrait_rounded,
      'Screen time',
      'When the screen is on, unlocks and how long sessions last.',
      Color(0xFF4ADE9B),
    ),
    'battery_state' => const _CollectorMeta(
      Icons.battery_std_rounded,
      'Battery',
      'Battery level and charging state.',
      Color(0xFFFFB55C),
    ),
    'active_window' => const _CollectorMeta(
      Icons.window_rounded,
      'Active window',
      'The app in front on your desktop. Great for focus insights.',
      Color(0xFF5B6CFF),
    ),
    'device_health' => const _CollectorMeta(
      Icons.health_and_safety_outlined,
      'Health checks',
      'Storage, memory and temperature warnings.',
      Color(0xFF9B6BFF),
    ),
    'idle_state' => const _CollectorMeta(
      Icons.timer_outlined,
      'Away time',
      'When you step away from the device.',
      Color(0xFF52D6E8),
    ),
    _ => _CollectorMeta(
      Icons.sensors_rounded,
      fallback,
      'An optional signal from this device.',
      const Color(0xFF5B6CFF),
    ),
  };
}

class _CollectorMeta {
  const _CollectorMeta(this.icon, this.title, this.description, this.color);

  final IconData icon;
  final String title;
  final String description;
  final Color color;
}

class _ConnectionCard extends StatelessWidget {
  const _ConnectionCard({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final device = controller.currentDevice;
    final snapshot = controller.syncSnapshot;
    final online =
        snapshot.state == SyncState.idle || snapshot.state == SyncState.syncing;
    return SectionCard(
      title: 'Your connection',
      subtitle: 'A quick, friendly summary of where this device is linked.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _ConnectionLine(
            icon: online ? Icons.verified_rounded : Icons.cloud_off_rounded,
            color: online ? const Color(0xFF4ADE9B) : const Color(0xFFFFB55C),
            title: online ? 'Connected' : 'Offline',
            subtitle: online
                ? 'Your VIRA server is reachable.'
                : 'Your data is waiting safely on this device.',
          ),
          const SizedBox(height: 10),
          _ConnectionLine(
            icon: Icons.dns_outlined,
            color: ViraPalette.indigo,
            title: _prettyServer(controller.serverUrl),
            subtitle: 'Your private VIRA server',
          ),
          const SizedBox(height: 10),
          _ConnectionLine(
            icon: Icons.devices_other_rounded,
            color: ViraPalette.violet,
            title:
                device?.displayName ??
                controller.settings.deviceName ??
                'This device',
            subtitle: 'This device',
          ),
          const SizedBox(height: 10),
          _ConnectionLine(
            icon: Icons.person_outline_rounded,
            color: ViraPalette.pink,
            title: controller.username ?? 'Signed in',
            subtitle: 'Your account',
          ),
          const SizedBox(height: 16),
          Text(
            'To see every linked device, open the Devices tab.',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ],
      ),
    );
  }

  String _prettyServer(String url) {
    final uri = Uri.tryParse(url);
    if (uri == null) return url;
    return uri.host.isEmpty ? url : uri.host;
  }
}

class _ConnectionLine extends StatelessWidget {
  const _ConnectionLine({
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        Container(
          width: 38,
          height: 38,
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.13),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Icon(icon, size: 19, color: color),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                subtitle,
                style: theme.textTheme.labelSmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _HowItWorks extends StatelessWidget {
  const _HowItWorks();

  @override
  Widget build(BuildContext context) {
    return GlassCard(
      padding: const EdgeInsets.all(18),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 720;
          final steps = [
            _Step(
              Icons.visibility_outlined,
              'It notices',
              'This device collects only the signals you switch on.',
            ),
            _Step(
              Icons.lock_outline_rounded,
              'It saves',
              'Everything is stored on your device first, so it is never lost.',
            ),
            _Step(
              Icons.cloud_sync_outlined,
              'It syncs',
              'When your server is reachable, it sends your data privately.',
            ),
          ];
          if (!wide) {
            return Column(
              children: [
                for (var index = 0; index < steps.length; index++) ...[
                  steps[index],
                  if (index != steps.length - 1) const SizedBox(height: 14),
                ],
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (var index = 0; index < steps.length; index++) ...[
                Expanded(child: steps[index]),
                if (index != steps.length - 1)
                  const Padding(
                    padding: EdgeInsets.fromLTRB(12, 10, 12, 0),
                    child: Icon(Icons.arrow_forward_rounded, size: 16),
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}

class _Step extends StatelessWidget {
  const _Step(this.icon, this.title, this.text);

  final IconData icon;
  final String title;
  final String text;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 20, color: theme.colorScheme.primary),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: theme.textTheme.bodyMedium?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                text,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                  height: 1.4,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _AdvancedDetails extends StatelessWidget {
  const _AdvancedDetails({required this.controller, required this.snapshot});

  final AppController controller;
  final SyncSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final device = controller.currentDevice;
    final profile = controller.profile;
    return GlassCard(
      padding: EdgeInsets.zero,
      child: Theme(
        data: theme.copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 4),
          childrenPadding: const EdgeInsets.fromLTRB(18, 0, 18, 16),
          leading: const Icon(Icons.terminal_rounded),
          title: const Text('Technical details'),
          subtitle: Text(
            'Device identifiers, queue and sync internals for advanced users.',
            style: theme.textTheme.bodySmall?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          children: [
            InfoRow(
              label: 'Device ID',
              value: controller.deviceId ?? 'Not enrolled',
              icon: Icons.fingerprint,
            ),
            InfoRow(
              label: 'Platform',
              value: device == null
                  ? '${profile?.platform ?? 'other'} · ${profile?.deviceType ?? ''}'
                  : '${device.platform} · ${device.deviceType}',
              icon: Icons.memory,
            ),
            InfoRow(
              label: 'Server',
              value: controller.serverUrl,
              icon: Icons.dns_outlined,
            ),
            InfoRow(
              label: 'Device status',
              value: device?.status ?? 'Unknown',
              icon: Icons.verified_user_outlined,
            ),
            InfoRow(
              label: 'Last seen',
              value: OutboxStore.prettyTime(device?.lastSeenAt),
              icon: Icons.visibility_outlined,
            ),
            InfoRow(
              label: 'Queued events',
              value: '${controller.pendingCount}',
              icon: Icons.inventory_2_outlined,
            ),
            InfoRow(
              label: 'Sent this session',
              value: '${snapshot.sentTotal}',
              icon: Icons.cloud_upload_outlined,
            ),
            InfoRow(
              label: 'Last sync',
              value: OutboxStore.prettyTime(snapshot.lastSync),
              icon: Icons.schedule,
            ),
            if (snapshot.lastError != null)
              InfoRow(
                label: 'Last error',
                value: snapshot.lastError!,
                icon: Icons.error_outline,
              ),
          ],
        ),
      ),
    );
  }
}
