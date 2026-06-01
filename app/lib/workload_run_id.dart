/// Stores the workload run UUID attached to Todo API requests.
///
/// The current value starts as `null`. Calling [set] with a valid UUID stores
/// its lowercase form so later Todo requests can send one stable
/// `x-workload-run-id` header value.
///
/// Example:
///   Setting `00000000-0000-0000-0000-000000000ABC` stores and returns
///   `00000000-0000-0000-0000-000000000abc`.
class WorkloadRunIdStore {
  String? get current => _current;

  String? _current;

  /// Validate and store one workload run UUID.
  ///
  /// Args:
  ///   value: UUID string supplied by the workload harness. Uppercase hex
  ///       characters are accepted and normalized to lowercase. Empty strings
  ///       and non-UUID values throw [FormatException] and leave [current]
  ///       unchanged.
  ///
  /// Returns:
  ///   The normalized lowercase UUID that was stored.
  ///
  /// Example:
  ///   `set('00000000-0000-0000-0000-000000000ABC')` returns
  ///   `00000000-0000-0000-0000-000000000abc`.
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
