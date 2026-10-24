"""RhineSign desktop entry point."""
import sys
if __name__ == "__main__":
    if len(sys.argv)==3 and sys.argv[1]=='--ui-self-test':
        from ui_self_test import run
        run(sys.argv[2])
    else:
        from window import main
        main()
