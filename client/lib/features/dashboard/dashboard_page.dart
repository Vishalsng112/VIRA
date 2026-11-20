import 'package:material_ui/material_ui.dart';

import '../../app/app_controller.dart';
import '../../app/app_scope.dart';
import '../../app/widgets.dart';
import '../../data/storage/outbox_store.dart';
import '../../services/capture/capture_service.dart';
import '../../services/sync/sync_service.dart';

class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final theme = Theme.of(context);
    final device = controller.currentDevice;
    final snapshot = controller.syncSnapshot;
    final activeCollectors = controller.collectors
        .where((item) => item.enabled && item.status == 'available')
        .length;
    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1120),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final wide = constraints.maxWidth > 680;
                      final info = Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              StatusPill(
                                label: _connectionLabel(snapshot.state),
                                tone: _connectionTone(snapshot.state),
                                icon: Icons.circle,
                              ),
                              const SizedBox(width: 8),
                              StatusPill(
                                label: '${controller.pendingCount} queued',
                                tone: controller.pendingCount == 0
                                    ? StatusTone.neutral
                                    : StatusTone.info,
                                icon: Icons.inventory_2_outlined,
                              ),
                            ],
                          ),
                          const SizedBox(height: 18),
                          Text(
                            device?.displayName ??
                                controller.settings.deviceName ??
                                'This device',
                            style: theme.textTheme.headlineMedium?.copyWith(
                              fontWeight: FontWeight.w700,
                              letterSpacing: -0.6,
                            ),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            'Linked to ${controller.serverUrl}',
                            style: theme.textTheme.bodyMedium?.copyWith(
                              color: theme.colorScheme.onSurfaceVariant,
                            ),
                          ),
                          if (snapshot.lastError != null) ...[
                            const SizedBox(height: 10),
                            Text(
                              snapshot.lastError!,
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: theme.colorScheme.error,
                              ),
                            ),
                          ],
                        ],
                      );
                      final actions = Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        children: [
                          FilledButton.icon(
                            onPressed: () => controller.syncNow(),
                            icon: const Icon(Icons.sync),
                            label: const Text('Sync now'),
                          ),
                          OutlinedButton.icon(
                            onPressed: () => controller.sendTestEvent(),
                            icon: const Icon(Icons.send_outlined),
                            label: const Text('Test event'),
                          ),
                        ],
                      );
                      if (!wide) {
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            info,
                            const SizedBox(height: 20),
                            actions,
                          ],
                        );
                      }
                      return Row(
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Expanded(child: info),
                          const SizedBox(width: 24),
                          actions,
                        ],
                      );
                    },
                  ),
                ),
              ),
              const SizedBox(height: 16),
              _Stats(
                pending: controller.pendingCount,
                sent: snapshot.sentTotal,
                lastSync: snapshot.lastSync,
                collectors: '$activeCollectors active',
              ),
              const SizedBox(height: 16),
              LayoutBuilder(
                builder: (context, constraints) {
                  final wide = constraints.maxWidth >= 860;
                  final capture = _CaptureCard(controller: controller);
                  final identity = _IdentityCard(controller: controller);
                  if (!wide) {
                    return Column(
                      children: [
                        capture,
                        const SizedBox(height: 16),
                        identity,
                      ],
                    );
                  }
                  return Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(flex: 3, child: capture),
                      const SizedBox(width: 16),
                      Expanded(flex: 2, child: identity),
                    ],
                  );
                },
              ),
              const SizedBox(height: 16),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(
                        Icons.info_outline,
                        color: theme.colorScheme.primary,
                      ),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Text(
                          'Capture runs locally. Every event is written to the device outbox first, '
                          'then sent to the device ingestion API in bounded batches. If the server is '
                          'unreachable, nothing is lost; the queue drains when it returns.',
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                            height: 1.5,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

String _connectionLabel(SyncState state) => switch (state) {
  SyncState.idle => 'Online',
  SyncState.syncing => 'Syncing',
  SyncState.offline => 'Offline',
  SyncState.error => 'Sync issue',
  SyncState.revoked => 'Revoked',
};

StatusTone _connectionTone(SyncState state) => switch (state) {
  SyncState.idle => StatusTone.success,
  SyncState.syncing => StatusTone.info,
  SyncState.offline => StatusTone.warning,
  SyncState.error => StatusTone.error,
  SyncState.revoked => StatusTone.error,
};

class _Stats extends StatelessWidget {
  const _Stats({
    required this.pending,
    required this.sent,
    required this.lastSync,
    required this.collectors,
  });

  final int pending;
  final int sent;
  final DateTime? lastSync;
  final String collectors;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      const spacing = 12.0;
      final columns = constraints.maxWidth >= 900
          ? 4
          : constraints.maxWidth >= 360
          ? 2
          : 1;
      final width =
          (constraints.maxWidth - spacing * (columns - 1)) / columns;
      final cards = [
        StatCard(
          icon: Icons.inventory_2_outlined,
          label: 'Queued events',
          value: '$pending',
          caption: pending == 0 ? 'Queue is empty' : 'Waiting to sync',
        ),
        StatCard(
          icon: Icons.cloud_upload_outlined,
          label: 'Sent this session',
          value: '$sent',
          caption: 'Accepted by the server',
        ),
        StatCard(
          icon: Icons.schedule,
          label: 'Last sync',
          value: OutboxStore.prettyClock(lastSync),
          caption: '${OutboxStore.prettyDay(lastSync)} · local time',
        ),
        StatCard(
          icon: Icons.sensors,
          label: 'Collectors',
          value: collectors,
          caption: 'Capture modules',
        ),
      ];
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

class _CaptureCard extends StatelessWidget {
  const _CaptureCard({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final List<CollectorState> collectors = controller.collectors;
    return SectionCard(
      title: 'Capture modules',
      subtitle: 'Enable only the signals this device should share.',
      trailing: FilledButton.tonalIcon(
        onPressed: () => controller.captureNow(),
        icon: const Icon(Icons.play_arrow),
        label: const Text('Capture now'),
      ),
      child: Column(
        children: [
          ...collectors.map(
            (state) => _CollectorTile(
              state: state,
              onChanged: (value) =>
                  controller.setCollectorEnabled(state.collector.id, value),
            ),
          ),
          if (collectors.isEmpty)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text('Starting capture service…'),
            ),
        ],
      ),
    );
  }
}

class _CollectorTile extends StatelessWidget {
  const _CollectorTile({required this.state, required this.onChanged});

  final CollectorState state;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (tone, label) = switch (state.status) {
      'available' => (StatusTone.success, 'Available'),
      'degraded' => (StatusTone.error, 'Degraded'),
      'permission_denied' => (StatusTone.warning, 'Permission denied'),
      _ => (StatusTone.neutral, 'Unavailable'),
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        state.collector.title,
                        style: theme.textTheme.bodyLarge?.copyWith(
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    StatusPill(label: label, tone: tone),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  state.collector.description,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                Text(
                  'Every ${state.collector.interval.inSeconds}s'
                  '${state.lastRun == null ? '' : ' · last ${OutboxStore.prettyTime(state.lastRun)}'}',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant.withValues(
                      alpha: 0.75,
                    ),
                  ),
                ),
              ],
            ),
          ),
          Switch(value: state.enabled, onChanged: onChanged),
        ],
      ),
    );
  }
}

class _IdentityCard extends StatelessWidget {
  const _IdentityCard({required this.controller});

  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final device = controller.currentDevice;
    final profile = controller.profile;
    return SectionCard(
      title: 'This device',
      subtitle: 'Identity issued by the VIRA server.',
      child: Column(
        children: [
          InfoRow(
            label: 'Name',
            value:
                device?.displayName ??
                controller.settings.deviceName ??
                'Unknown',
            icon: Icons.label_outline,
          ),
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
            label: 'Server status',
            value: device?.status ?? 'Unknown',
            icon: Icons.dns_outlined,
          ),
          InfoRow(
            label: 'Last seen',
            value: OutboxStore.prettyTime(device?.lastSeenAt),
            icon: Icons.visibility_outlined,
          ),
        ],
      ),
    );
  }
}
