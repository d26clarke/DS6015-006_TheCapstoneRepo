export interface TreeInventoryRecord {
  treeId: string; // Format: TREE-XXXXX
  tagNumber: number | null;
  scientificName: string;
  commonName: string;
  dbhInches: number;
  totalHeightFt: number | null;
  canopyRadiusFt: number | null;
  heightToCrownBaseFt: number | null;
  numberOfTrunks: number;
  conditionClass: 'Excellent' | 'Good' | 'Fair' | 'Poor' | 'Dead' | null;
  diebackPercentage: '0-10%' | '11-25%' | '26-50%' | '50%+' | null;
  pestDiseasePresent: 'None' | 'Spotted Lanternfly' | 'Emerald Ash Borer' | 'Oak Wilt' | 'Other' | null;
  structuralDefects: string | null;
  gpsCoordinates: string; // "Lat, Long"
  landUseType: 'Riparian Buffer' | 'Urban Park' | 'Street Tree' | 'Forested Wetland' | null;
  soilMoistureRegime: 'Poorly Drained (Wet)' | 'Moderately Drained' | 'Well Drained (Dry)' | null;
  surroundingSurface: 'Soil/Mulch' | 'Turf Grass' | 'Permeable Pavers' | 'Concrete/Asphalt' | null;
  insertDate: string; // YYYY-MM-DD
  lastUpdate: string; // YYYY-MM-DD
  teamMembers: string;
  notes: string | null;
  photoUrl: string | null; // CloudFront distribution URL
}

