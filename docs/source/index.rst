.. hyper-h2 documentation master file, created by
   sphinx-quickstart on Thu Sep 17 10:06:02 2015.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Hyper-h2: A pure-Python HTTP/2 protocol stack
=============================================

Hyper-h2 is a HTTP/2 protocol stack, written entirely in Python. The goal of
hyper-h2 is to be a common HTTP/2 implementation for the Python ecosystem,
usable in all programs regardless of concurrency model or environment.

To achieve this, hyper-h2 is entirely self-contained: it does no I/O of any
kind, leaving that up to a wrapper library to control. This ensures that it can
seamlessly work in all kinds of environments, from single-threaded code to
Twisted.

Its goal is to be 100% compatible with RFC 7540, implementing a complete HTTP/2
protocol stack build on a set of finite state machines. Its secondary goals are
to be fast, clear, and efficient.

This documentation is currently under construction. Please check back later.

Contents:

.. toctree::
   :maxdepth: 2
