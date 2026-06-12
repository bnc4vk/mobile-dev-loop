# Private Experiment Assets

This directory is committed for planning visibility only. During real experimental runs, executor worktrees must exclude `experiment/private/` so agents cannot read validators, expected patch references, or fault-injection controls.

Evaluator threads may access this directory. Builder and executor threads should not use it during baseline/candidate task execution.
