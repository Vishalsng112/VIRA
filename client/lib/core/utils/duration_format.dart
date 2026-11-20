String formatDurationMs(int milliseconds) {
  if (milliseconds <= 0) return '0m';
  final minutes = milliseconds ~/ 60000;
  if (minutes < 60) return '${minutes < 1 ? 1 : minutes}m';
  final hours = minutes ~/ 60;
  final remainder = minutes % 60;
  return remainder == 0 ? '${hours}h' : '${hours}h ${remainder}m';
}
