"""Generate an authored EPUB for local ebook pipeline integration testing."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import zipfile

PROJECT = Path(__file__).resolve().parent


def generate(folder=None):
    folder = Path(folder) if folder is not None else PROJECT / '.cache' / 'fixtures'
    if '..' in folder.parts:
        raise ValueError('Parent traversal is not allowed')
    folder = folder.absolute()
    if not folder.is_relative_to(PROJECT):
        raise ValueError('Fixture folder must be inside this workspace')
    for part in (folder, *folder.parents):
        if part.is_symlink():
            raise ValueError('Symlinked fixture folder rejected')
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'ebook-pipeline-smoke-test.epub'
    modified = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    documents = {
        'META-INF/container.xml': '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/package.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''',
        'EPUB/package.opf': f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="en"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">urn:uuid:c87bb4a6-38e2-4cfe-9f47-287a39eb71d6</dc:identifier><dc:title>Ebook Pipeline Smoke Test</dc:title><dc:language>en</dc:language><dc:creator>Local Pipeline Tester</dc:creator><dc:rights>Original local test content; permission granted to copy and use for pipeline testing.</dc:rights><meta property="dcterms:modified">{modified}</meta></metadata><manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chapter"/></spine></package>''',
        'EPUB/nav.xhtml': '''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en" lang="en"><head><title>Contents</title></head><body><nav epub:type="toc" id="toc"><h1>Contents</h1><ol><li><a href="chapter.xhtml">Pipeline smoke test</a></li></ol></nav></body></html>''',
        'EPUB/chapter.xhtml': '''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en" lang="en"><head><title>Ebook Pipeline Smoke Test</title></head><body><h1>Ebook Pipeline Smoke Test</h1><p>Authored locally for this deployment's integration tests. This EPUB contains original test prose, with no downloaded book content.</p><p>A small lantern rests beside a blue notebook. The reader opens the first page and finds a clear sentence, a working contents link, and a quiet ending.</p><p>Confirm this title, navigation, and text on the physical Kindle. An SMTP success message alone does not prove delivery.</p></body></html>''',
    }
    with zipfile.ZipFile(path, 'x') as archive:
        archive.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        for name, content in documents.items():
            archive.writestr(name, content, compress_type=zipfile.ZIP_DEFLATED)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--temp-folder', type=Path, help='Folder inside workspace (default: .cache/fixtures)')
    args = parser.parse_args()
    print(generate(args.temp_folder))


if __name__ == '__main__':
    main()
