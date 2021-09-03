#!/usr/bin/env python
import atheris
import sys

with atheris.instrument_imports():
  import h2.connection
  import h2.config
  from h2.exceptions import ProtocolError

def TestOneInput(data):
    config = h2.config.H2Configuration(client_side=False)
    conn = h2.connection.H2Connection(config=config)
    try:
      conn.receive_data(data)
    except ProtocolError:
      pass

if __name__ == "__main__":
  atheris.Setup(sys.argv, TestOneInput)
  atheris.Fuzz()