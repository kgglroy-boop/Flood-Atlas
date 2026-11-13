<?xml version="1.0" encoding="UTF-8"?><sld:StyledLayerDescriptor xmlns:sld="http://www.opengis.net/sld" xmlns="http://www.opengis.net/sld" xmlns:gml="http://www.opengis.net/gml" xmlns:ogc="http://www.opengis.net/ogc" version="1.0.0">
  <sld:NamedLayer>
    <sld:Name>depth_teaching</sld:Name>
    <sld:UserStyle>
      <sld:Name>depth_teaching</sld:Name>
      <sld:Title>教学水深 m · depth &gt; 0.10</sld:Title>
      <sld:FeatureTypeStyle>
        <sld:Name>name</sld:Name>
        <sld:Rule>
          <sld:RasterSymbolizer>
            <sld:ColorMap extended="true">
              <sld:ColorMapEntry color="#ffffff" opacity="0" quantity="-9999" label="NoData"/>
              <sld:ColorMapEntry color="#ffffff" opacity="0" quantity="0" label="Dry"/>
              <sld:ColorMapEntry color="#d6eef0" opacity="0" quantity="0.10000000149011612" label="Threshold"/>
              <sld:ColorMapEntry color="#d6eef0" opacity="1" quantity="0.101" label="0.101 m"/>
              <sld:ColorMapEntry color="#a8dce4" opacity="1" quantity="0.3" label="0.3 m"/>
              <sld:ColorMapEntry color="#69bfd0" opacity="1" quantity="0.6" label="0.6 m"/>
              <sld:ColorMapEntry color="#3297b5" opacity="1" quantity="1" label="1 m"/>
              <sld:ColorMapEntry color="#146a91" opacity="1" quantity="1.5" label="1.5 m"/>
              <sld:ColorMapEntry color="#103f67" opacity="1" quantity="2" label="2 m"/>
            </sld:ColorMap>
            <sld:ContrastEnhancement/>
          </sld:RasterSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </sld:NamedLayer>
</sld:StyledLayerDescriptor>


