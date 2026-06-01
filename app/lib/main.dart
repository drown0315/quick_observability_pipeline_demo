import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:todo_app/workload_run_id.dart' as workload;

const _appEnvironment = String.fromEnvironment(
  'APP_ENVIRONMENT',
  defaultValue: 'local',
);
const _appRelease = String.fromEnvironment(
  'APP_RELEASE',
  defaultValue: 'local',
);
const _sentryDsn = String.fromEnvironment('SENTRY_DSN');

Future<void> main() async {
  final sessionId = SentryId.newId().toString();
  await SentryFlutter.init(
    (options) {
      options.dsn = _sentryDsn;
      options.release = _appRelease;
      options.environment = _appEnvironment;
      options.sendDefaultPii = false;
      options.enableLogs = false;
    },
    appRunner: () async {
      await Sentry.configureScope((scope) async {
        await scope.setUser(SentryUser(id: 'demo-user'));
        await scope.setTag('session_id', sessionId);
      });
      runApp(const TodoApp());
    },
  );
}

class Todo {
  const Todo({required this.id, required this.title, required this.completed});

  factory Todo.fromJson(Map<String, dynamic> json) {
    return Todo(
      id: json['id'] as int,
      title: json['title'] as String,
      completed: json['completed'] as bool,
    );
  }

  final int id;
  final String title;
  final bool completed;
}

abstract class TodoRepository {
  Future<List<Todo>> listTodos();
  Future<Todo> createTodo(String title);
  Future<Todo> setCompleted(int id, bool completed);
  Future<void> deleteTodo(int id);
}

class HttpTodoRepository implements TodoRepository {
  HttpTodoRepository({
    http.Client? client,
    workload.WorkloadRunIdStore? workloadRunIdStore,
    this._baseUrl = const String.fromEnvironment(
      'TODO_API_BASE_URL',
      defaultValue: 'http://localhost:8000',
    ),
  })  : _client = client ?? http.Client(),
        _workloadRunIdStore = workloadRunIdStore ?? workload.workloadRunIdStore;

  final http.Client _client;
  final workload.WorkloadRunIdStore _workloadRunIdStore;
  final String _baseUrl;

  @override
  Future<List<Todo>> listTodos() async {
    final response = await _client.get(
      Uri.parse('$_baseUrl/todos'),
      headers: _headers(),
    );
    _requireSuccess(response);
    return (jsonDecode(response.body) as List<dynamic>)
        .map((json) => Todo.fromJson(json as Map<String, dynamic>))
        .toList();
  }

  @override
  Future<Todo> createTodo(String title) async {
    final response = await _client.post(
      Uri.parse('$_baseUrl/todos'),
      headers: _headers(includeJsonContentType: true),
      body: jsonEncode({'title': title}),
    );
    _requireSuccess(response);
    return Todo.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  @override
  Future<Todo> setCompleted(int id, bool completed) async {
    final response = await _client.patch(
      Uri.parse('$_baseUrl/todos/$id'),
      headers: _headers(includeJsonContentType: true),
      body: jsonEncode({'completed': completed}),
    );
    _requireSuccess(response);
    return Todo.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
  }

  @override
  Future<void> deleteTodo(int id) async {
    final response = await _client.delete(
      Uri.parse('$_baseUrl/todos/$id'),
      headers: _headers(),
    );
    _requireSuccess(response);
  }

  Map<String, String> _headers({bool includeJsonContentType = false}) {
    final runId = _workloadRunIdStore.current;
    return {
      if (includeJsonContentType) 'content-type': 'application/json',
      if (runId != null) 'x-workload-run-id': runId,
    };
  }

  void _requireSuccess(http.Response response) {
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Todo API returned ${response.statusCode}');
    }
  }
}

class TodoApp extends StatelessWidget {
  const TodoApp({super.key, this.repository});

  final TodoRepository? repository;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Todo',
      navigatorObservers: [SentryNavigatorObserver()],
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
      ),
      home: TodoPage(repository: repository ?? HttpTodoRepository()),
    );
  }
}

class TodoPage extends StatefulWidget {
  const TodoPage({super.key, required this.repository});

  final TodoRepository repository;

  @override
  State<TodoPage> createState() => _TodoPageState();
}

class _TodoPageState extends State<TodoPage> {
  final _titleController = TextEditingController();
  List<Todo> _todos = [];
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadTodos();
  }

  @override
  void dispose() {
    _titleController.dispose();
    super.dispose();
  }

  Future<void> _loadTodos() async {
    await _perform(() async {
      _todos = await widget.repository.listTodos();
    });
  }

  Future<void> _createTodo() async {
    final title = _titleController.text.trim();
    if (title.isEmpty) {
      return;
    }
    await _perform(() async {
      _todos = [..._todos, await widget.repository.createTodo(title)];
      _titleController.clear();
    });
  }

  Future<void> _setCompleted(Todo todo, bool completed) async {
    await _perform(() async {
      final updated = await widget.repository.setCompleted(todo.id, completed);
      _todos = [
        for (final current in _todos)
          if (current.id == todo.id) updated else current,
      ];
    });
  }

  Future<void> _deleteTodo(Todo todo) async {
    await _perform(() async {
      await widget.repository.deleteTodo(todo.id);
      _todos = _todos.where((current) => current.id != todo.id).toList();
    });
  }

  Future<void> _perform(Future<void> Function() operation) async {
    setState(() {
      _error = null;
      _loading = true;
    });
    try {
      await operation();
    } catch (error) {
      _error = error.toString();
    } finally {
      if (mounted) {
        setState(() {
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Todo'),
        actions: [
          if (kDebugMode)
            IconButton(
              key: const Key('trigger-client-exception'),
              tooltip: 'Trigger temporary client exception',
              onPressed: () {
                throw StateError('temporary client exception');
              },
              icon: const Icon(Icons.bug_report),
            ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          children: [
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: const Key('new-todo-title'),
                    controller: _titleController,
                    decoration: const InputDecoration(
                      border: OutlineInputBorder(),
                      labelText: 'New Todo',
                    ),
                    onSubmitted: (_) => _createTodo(),
                  ),
                ),
                const SizedBox(width: 12),
                FilledButton(
                  key: const Key('add-todo'),
                  onPressed: _loading ? null : _createTodo,
                  child: const Text('Add'),
                ),
              ],
            ),
            if (_loading) const LinearProgressIndicator(),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(_error!, style: const TextStyle(color: Colors.red)),
              ),
            const SizedBox(height: 12),
            Expanded(
              child: ListView(
                children: [
                  for (final todo in _todos)
                    ListTile(
                      key: Key('todo-${todo.id}'),
                      leading: Checkbox(
                        value: todo.completed,
                        onChanged: _loading
                            ? null
                            : (completed) =>
                                _setCompleted(todo, completed ?? false),
                      ),
                      title: Text(
                        todo.title,
                        style: TextStyle(
                          decoration: todo.completed
                              ? TextDecoration.lineThrough
                              : null,
                        ),
                      ),
                      trailing: IconButton(
                        tooltip: 'Delete ${todo.title}',
                        onPressed: _loading ? null : () => _deleteTodo(todo),
                        icon: const Icon(Icons.delete),
                      ),
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
