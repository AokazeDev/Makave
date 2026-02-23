from src.cli import parse_args


def main() -> None:
    from src.pipeline import run

    config = parse_args()
    run(config)


if __name__ == "__main__":
    main()