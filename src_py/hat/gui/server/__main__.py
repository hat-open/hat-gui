import sys

from hat.gui.server.main import main


if __name__ == '__main__':
    sys.argv[0] = 'hat-gui-server'
    sys.exit(main())
