<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor version="1.0.0" xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc">
  <NamedLayer><Name>depth_teaching</Name><UserStyle><Name>depth_teaching</Name>
    <Title>教学水深 m · depth &gt; 0.10</Title>
    <FeatureTypeStyle><Rule><RasterSymbolizer><Opacity>1</Opacity>
      <ColorMap type="ramp" extended="true">
        <ColorMapEntry color="#ffffff" quantity="-9999" opacity="0" label="NoData"/>
        <ColorMapEntry color="#ffffff" quantity="0" opacity="0" label="Dry"/>
        <ColorMapEntry color="#d6eef0" quantity="0.10000000149011612" opacity="0" label="Threshold"/>
        <ColorMapEntry color="#d6eef0" quantity="0.101" opacity="1" label="0.101 m"/>
        <ColorMapEntry color="#a8dce4" quantity="0.3" opacity="1" label="0.3 m"/>
        <ColorMapEntry color="#69bfd0" quantity="0.6" opacity="1" label="0.6 m"/>
        <ColorMapEntry color="#3297b5" quantity="1" opacity="1" label="1 m"/>
        <ColorMapEntry color="#146a91" quantity="1.5" opacity="1" label="1.5 m"/>
        <ColorMapEntry color="#103f67" quantity="2" opacity="1" label="2 m"/>
      </ColorMap>
    </RasterSymbolizer></Rule></FeatureTypeStyle>
  </UserStyle></NamedLayer>
</StyledLayerDescriptor>
