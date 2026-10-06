from lxml import etree


def test_internal_entity_mode_does_not_load_external_parameter_entities():
    requested = []

    class ExternalEntityProbe(etree.Resolver):
        def resolve(self, url, public_id, context):
            requested.append(url)
            return self.resolve_string('<!ENTITY canary "outside-source-canary">', context)

    parser = etree.XMLParser(load_dtd=True, resolve_entities="internal", no_network=True)
    parser.resolvers.add(ExternalEntityProbe())
    payload = b'<!DOCTYPE root [<!ENTITY % ext SYSTEM "file:///extrio-qa-outside-source.dtd">%ext;]><root>&canary;</root>'
    try:
        root = etree.fromstring(payload, parser)
    except etree.XMLSyntaxError:
        root = None
    assert requested == []
    assert root is None or root.text != "outside-source-canary"


def test_internal_entity_mode_preserves_internal_entities():
    parser = etree.XMLParser(load_dtd=True, resolve_entities="internal", no_network=True)
    root = etree.fromstring(b'<!DOCTYPE root [<!ENTITY local "safe-source-text">]><root>&local;</root>', parser)
    assert root.text == "safe-source-text"
