# Fuzzing

This directory contains code and test data for fuzz testing `h2` with [Atheris](https://github.com/google/atheris) which bring [LibFuzzer](http://llvm.org/docs/LibFuzzer.html) to Python world.

## Test corpus information

The test corpus included in directory `corpus` were initially created by patching `h2` to store all data pass to `H2Connection.receive_data` and then running the unit tests. The corpus were then broadened via fuzzing with this fuzzer and minimized. See the [LibFuzzer docs](http://llvm.org/docs/LibFuzzer.html) for more information on how minimization works.

## Running the fuzzers

You will likely want to adjust fuzzer options to your execution environment, but here are basic examples of running each fuzzer:

* Client: `python ./h2_client_fuzzer.py ./corpus/`
* Server: `python ./h2_server_fuzzer.py ./corpus/`

See the [LibFuzzer docs](https://llvm.org/docs/LibFuzzer.html#options) for list of available options.

If new errors are found, test input file will be created in current working directory and the program will exit.

If a list of files (rather than directories) are passed to the fuzzer, then it will re-run those files as test inputs. This allows you to verify fix for particular test input. When submitting a bug fix to the project, be sure to add test input file to corpus dictionary to avoid regression.

## Submitting new seed files

`h2` welcomes contributions to add seed files that exercise new paths by fuzzer. Before submitting new seed files, please ensure they add coverage to the existing corpus via `-merge` flag. For example:

```bash
$ python ./h2_client_fuzzer.py -merge=1 ./corpus ./my-new-seeds
$ python ./h2_server_fuzzer.py -merge=1 ./corpus ./my-new-seeds
```
