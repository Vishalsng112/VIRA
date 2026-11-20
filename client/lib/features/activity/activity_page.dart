import 'package:material_ui/material_ui.dart';

import '../../app/app_scope.dart';
import '../../app/widgets.dart';
import '../../core/models/captured_event.dart';
import '../../data/storage/outbox_store.dart';

enum _ActivityView { pending, history }

class ActivityPage extends StatefulWidget {
  const ActivityPage({super.key});

  @override
  State<ActivityPage> createState() => _ActivityPageState();
}

class _ActivityPageState extends State<ActivityPage> {
  _ActivityView _view = _ActivityView.pending;
  List<CapturedEvent> _pending = const [];
  List<CapturedEvent> _history = const [];
  bool _loading = true;
  bool _autoSelected = false;

  @override
  void initState() {
    super.initState();
    final controller = AppScope.of(context, listen: false);
    controller.addListener(_reload);
    _load();
  }

  @override
  void dispose() {
    AppScope.of(context, listen: false).removeListener(_reload);
    super.dispose();
  }

  void _reload() {
    if (mounted) _load();
  }

  Future<void> _load() async {
    final controller = AppScope.of(context, listen: false);
    final pending = await controller.pendingEvents(limit: 200);
    final history = await controller.historyEvents();
    if (!mounted) return;
    setState(() {
      _pending = pending.reversed.toList();
      _history = history;
      _loading = false;
      if (!_autoSelected) {
        _autoSelected = true;
        if (_pending.isEmpty && _history.isNotEmpty) {
          _view = _ActivityView.history;
        }
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final controller = AppScope.of(context);
    final theme = Theme.of(context);
    final items = _view == _ActivityView.pending ? _pending : _history;
    return Padding(
      padding: const EdgeInsets.all(20),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 980),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Device activity',
                          style: theme.textTheme.headlineSmall?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Everything captured here is stored locally first.',
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (_view == _ActivityView.history && _history.isNotEmpty)
                    TextButton.icon(
                      onPressed: () async {
                        await controller.clearHistory();
                        await _load();
                      },
                      icon: const Icon(Icons.delete_sweep_outlined),
                      label: const Text('Clear'),
                    ),
                ],
              ),
              const SizedBox(height: 16),
              SegmentedButton<_ActivityView>(
                segments: [
                  ButtonSegment(
                    value: _ActivityView.pending,
                    icon: const Icon(Icons.inventory_2_outlined),
                    label: Text('Queued (${_pending.length})'),
                  ),
                  ButtonSegment(
                    value: _ActivityView.history,
                    icon: const Icon(Icons.history),
                    label: Text('History (${_history.length})'),
                  ),
                ],
                selected: {_view},
                onSelectionChanged: (value) =>
                    setState(() => _view = value.first),
              ),
              const SizedBox(height: 16),
              Expanded(
                child: _loading
                    ? const Center(child: CircularProgressIndicator())
                    : items.isEmpty
                    ? EmptyState(
                        icon: _view == _ActivityView.pending
                            ? Icons.inbox_outlined
                            : Icons.history,
                        title: _view == _ActivityView.pending
                            ? 'The outbox is empty'
                            : 'No history yet',
                        message: _view == _ActivityView.pending
                            ? 'Captured events appear here until the server acknowledges them.'
                            : 'Sent and rejected events are logged locally for troubleshooting.',
                      )
                    : RefreshIndicator(
                        onRefresh: _load,
                        child: ListView.separated(
                          itemCount: items.length,
                          separatorBuilder: (_, _) => const SizedBox(height: 8),
                          itemBuilder: (context, index) =>
                              _EventTile(event: items[index]),
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

class _EventTile extends StatelessWidget {
  const _EventTile({required this.event});

  final CapturedEvent event;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (tone, label, icon) = switch (event.deliveryState) {
      EventDeliveryState.pending => (
        StatusTone.warning,
        'Queued',
        Icons.schedule,
      ),
      EventDeliveryState.sent => (
        StatusTone.success,
        'Sent',
        Icons.check_circle_outline,
      ),
      EventDeliveryState.rejected => (
        StatusTone.error,
        'Rejected',
        Icons.error_outline,
      ),
    };
    return Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(icon, size: 20, color: theme.colorScheme.primary),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          event.type,
                          style: theme.textTheme.bodyLarge?.copyWith(
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                      StatusPill(label: label, tone: tone),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${event.sourceComponent} · ${OutboxStore.prettyTime(event.occurredAt)}'
                    '${event.deviceSequence == null ? '' : ' · seq ${event.deviceSequence}'}',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                  if (event.error != null) ...[
                    const SizedBox(height: 4),
                    Text(
                      event.error!,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.error,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
