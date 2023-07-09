import pytest

from hat import aio


def pytest_addoption(parser):
    parser.addoption("--unit",
                     action="store_true",
                     help="run unit tests")
    parser.addoption("--sys",
                     action="store_true",
                     help="run system tests")
    parser.addoption("--perf",
                     action="store_true",
                     help="run performance tests")


def pytest_configure(config):
    aio.init_asyncio()
    config.addinivalue_line("markers", "unit: mark unit test")
    config.addinivalue_line("markers", "sys: mark system test")
    config.addinivalue_line("markers", "perf: mark performance test")


def pytest_runtest_setup(item):
    options = {option for option in ['unit', 'sys', 'perf']
               if item.config.getoption(f'--{option}')}
    if not options:
        options.add('unit')

    marks = {mark for mark in ['unit', 'sys', 'perf']
             if any(item.iter_markers(name=mark))}
    if not marks:
        marks.add('unit')

    if options.isdisjoint(marks):
        pytest.skip("test not marked for execution")
