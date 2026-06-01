class WorkloadRunIdStore {
  String? get current => _current;

  String? _current;

  String set(String value) {
    final normalized = value.toLowerCase();
    if (!_uuidPattern.hasMatch(normalized)) {
      throw const FormatException('Workload run ID must be a UUID');
    }
    _current = normalized;
    return normalized;
  }

  static final _uuidPattern = RegExp(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
  );
}

final workloadRunIdStore = WorkloadRunIdStore();
