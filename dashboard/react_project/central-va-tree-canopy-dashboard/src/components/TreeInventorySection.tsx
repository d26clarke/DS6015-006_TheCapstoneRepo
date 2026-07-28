import React, { useState, useEffect } from 'react';

// 1. Native Interface Definition inside the file 
interface TreeInventoryRecord {
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

// Configuration variables pointing to your API Architecture
// Single API Gateway (tree-canopy-public-gateway / rqmo3xlicl) handles both
// the Postgres CRUD routes and photo-upload-url -- there is no separate
// Node.js/multer upload server; that was aspirational/incorrect in an
// earlier version of this file.
const AWS_API_GATEWAY_URL = 'https://rqmo3xlicl.execute-api.us-east-1.amazonaws.com';

const BLANK_FORM: Omit<TreeInventoryRecord, 'treeId'> & { treeId: string } = {
  treeId: '',
  tagNumber: null,
  scientificName: '',
  commonName: '',
  dbhInches: 0,
  totalHeightFt: null,
  canopyRadiusFt: null,
  heightToCrownBaseFt: null,
  numberOfTrunks: 1,
  conditionClass: null,
  diebackPercentage: null,
  pestDiseasePresent: null,
  structuralDefects: null,
  gpsCoordinates: '',
  landUseType: null,
  soilMoistureRegime: null,
  surroundingSurface: null,
  insertDate: new Date().toISOString().split('T')[0],
  lastUpdate: new Date().toISOString().split('T')[0],
  teamMembers: '',
  notes: null,
  photoUrl: null
};

export default function TreeInventorySection() {
  const [trees, setTrees] = useState<TreeInventoryRecord[]>([]);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [isEditing, setIsEditing] = useState<boolean>(false);
  const [formData, setFormData] = useState(BLANK_FORM);
  
  // File upload state controls
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(false);

// Converts the Lambda's raw Postgres response (snake_case column names,
// e.g. tree_id, common_name) into the camelCase shape TreeInventoryRecord
// and the rest of this component expect. Necessary because RealDictCursor
// in the Lambda preserves native Postgres column naming with no
// transformation -- without this, every read (search filter, table
// display, edit population) silently breaks since e.g. tree.treeId simply
// doesn't exist on the real response object (it's tree.tree_id).
function toCamelCase<T>(row: Record<string, unknown>): T {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    const camelKey = key.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
    result[camelKey] = value;
  }
  return result as T;
}

  // 🔍 READ ALL: Pull dataset out of your canopy_dashboard PostgreSQL cluster
  const fetchTrees = async () => {
    setIsLoading(true);
    try {
      // Maps to your Lambda GET routing pipeline
      const response = await fetch(`${AWS_API_GATEWAY_URL}/api/trees`);
      if (!response.ok) throw new Error('Failed to retrieve inventory tables.');
      const data = await response.json();
      const rows = Array.isArray(data) ? data : [];
      setTrees(rows.map((row) => toCamelCase<TreeInventoryRecord>(row)));
    } catch (error) {
      console.error(error);
      alert('Network Connectivity Error: Unable to sync with AWS Lambda API.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchTrees();
  }, []);

  // Client-Side Live search lookup utility
  const filteredTrees = trees.filter(tree => 
    tree.treeId?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    tree.commonName?.toLowerCase().includes(searchTerm.toLowerCase()) ||
    tree.scientificName?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    const { name, value, type } = e.target;
    let processedValue: any = value;

    if (type === 'number') {
      processedValue = value === '' ? null : Number(value);
    } else if (value === '') {
      processedValue = null;
    }

    setFormData(prev => ({ ...prev, [name]: processedValue }));
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
    }
  };

  // 📷 Direct browser-to-S3 upload via a presigned URL.
  // Flow: ask the Lambda for a short-lived presigned PUT URL (scoped to
  // s3://central-va-tree-canopy-dashboard/data/tree-photos/{treeId}/...),
  // then PUT the actual file bytes straight to S3 -- the Lambda/API Gateway
  // never sees the binary data, avoiding their ~6MB payload limit entirely.
  // Returns the public (CloudFront) URL to store as photoUrl, or null on failure.
  const uploadImageToS3 = async (treeId: string): Promise<string | null> => {
    if (!selectedFile) return null;
    setIsUploading(true);

    try {
      const contentType = selectedFile.type || 'image/jpeg';
      const fileExtension = selectedFile.name.includes('.')
        ? '.' + selectedFile.name.split('.').pop()
        : '.jpg';

      // Step 1: ask the Lambda for a presigned upload URL
      const urlResponse = await fetch(`${AWS_API_GATEWAY_URL}/api/trees/${treeId}/photo-upload-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contentType, fileExtension }),
      });
      if (!urlResponse.ok) throw new Error('Could not obtain an S3 upload URL from the API.');
      const { uploadUrl, publicUrl } = await urlResponse.json();

      // Step 2: PUT the actual file bytes directly to S3. The Content-Type
      // header here MUST match what was sent when requesting the presigned
      // URL above, or S3 will reject the request with SignatureDoesNotMatch.
      const putResponse = await fetch(uploadUrl, {
        method: 'PUT',
        headers: { 'Content-Type': contentType },
        body: selectedFile,
      });
      if (!putResponse.ok) throw new Error('S3 rejected the direct photo upload.');

      return publicUrl;
    } catch (error) {
      console.error(error);
      alert('AWS S3 Integration Failure: Field photo failed to push onto cloud bucket.');
      return null;
    } finally {
      setIsUploading(false);
      setSelectedFile(null);
    }
  };

  // 💾 SUBMIT PIPELINE: Coordinates Cloud Asset storage uploads with the Postgres mutation
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!/^TREE-\d{5}$/.test(formData.treeId)) {
      return alert('Validation Exception: Tree ID format rules require strict syntax structure (e.g., TREE-00142).');
    }

    try {
      // Phase 1: if a new photo was selected, upload it FIRST so its real
      // URL can be included in the record we're about to save -- doing
      // this after the save (as before) meant the resulting photoUrl was
      // never actually persisted to the database at all.
      let photoUrl = formData.photoUrl;
      if (selectedFile) {
        const uploadedUrl = await uploadImageToS3(formData.treeId);
        if (!uploadedUrl) return; // upload failed -- don't save a record with a stale/missing photo
        photoUrl = uploadedUrl;
      }

      // Target API Gateway URLs based on your CRUD Lambda paths
      const url = isEditing 
        ? `${AWS_API_GATEWAY_URL}/api/trees/${formData.treeId}`
        : `${AWS_API_GATEWAY_URL}/api/trees`;

      const method = isEditing ? 'PUT' : 'POST';
      
      const updatedFormData = {
        ...formData,
        photoUrl,
        lastUpdate: new Date().toISOString().split('T')[0]
      };

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatedFormData),
      });

      if (!response.ok) throw new Error('AWS Lambda transaction failed processing database parameters.');

      alert(isEditing ? 'Tree inventory record mutated successfully.' : 'New database tree committed successfully.');
      setFormData(BLANK_FORM);
      setIsEditing(false);
      fetchTrees();
    } catch (error) {
      console.error(error);
      alert('API Integration Error: Transaction dropped at cloud ingress border.');
    }
  };

  // ❌ DELETE Pipeline Engine Trigger mapping directly to database execution commands
  const handleDelete = async (treeId: string) => {
    if (!window.confirm(`Purge tree log ${treeId} permanently from canopy_dashboard? This cannot be undone.`)) return;

    try {
      const response = await fetch(`${AWS_API_GATEWAY_URL}/api/trees/${treeId}`, {
        method: 'DELETE',
      });

      if (!response.ok) throw new Error('Target index deletion rejected by database layer.');
      
      alert('Registry entry successfully purged.');
      fetchTrees();
    } catch (error) {
      console.error(error);
      alert('Transaction Error: Failed to wipe tree record context.');
    }
  };

  const startEdit = (tree: TreeInventoryRecord) => {
    setIsEditing(true);
    setFormData({
      treeId: tree.treeId,
      tagNumber: tree.tagNumber,
      scientificName: tree.scientificName,
      commonName: tree.commonName,
      dbhInches: tree.dbhInches,
      totalHeightFt: tree.totalHeightFt,
      canopyRadiusFt: tree.canopyRadiusFt,
      heightToCrownBaseFt: tree.heightToCrownBaseFt,
      numberOfTrunks: tree.numberOfTrunks,
      conditionClass: tree.conditionClass,
      diebackPercentage: tree.diebackPercentage,
      pestDiseasePresent: tree.pestDiseasePresent,
      structuralDefects: tree.structuralDefects,
      gpsCoordinates: tree.gpsCoordinates,
      landUseType: tree.landUseType,
      soilMoistureRegime: tree.soilMoistureRegime,
      surroundingSurface: tree.surroundingSurface,
      insertDate: tree.insertDate ? tree.insertDate.split('T')[0] : new Date().toISOString().split('T')[0],
      lastUpdate: new Date().toISOString().split('T')[0],
      teamMembers: tree.teamMembers,
      notes: tree.notes,
      photoUrl: tree.photoUrl
    });
  };

  return (
    <section style={{ padding: '2rem', maxWidth: '1600px', margin: '0 auto' }}>
      <h2 style={{ fontSize: '1.75rem', color: '#1a365d', marginBottom: '1.5rem' }}>🌲 Field Tree Registry System</h2>
      
      {/* Search Input Box */}
      <div style={{ marginBottom: '1.5rem' }}>
        <input 
          type="text" 
          placeholder="Filter field trees by Tree ID, Common Name, or Scientific Name..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          style={{ width: '100%', padding: '0.75rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '1rem' }}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: '2rem', alignItems: 'start' }}>

        {/* ==========================================
          LEFT COLUMN: Input Form Sidebar Panel
         ========================================== */}
        
        {/* Full Fields Unified Input Form Layout */}
        <div style={{ background: '#f8fafc', padding: '1.5rem', borderRadius: '8px', border: '1px solid #e2e8f0', maxHeight: '85vh', overflowY: 'auto' }}>
          <h3 style={{ fontSize: '1.2rem', marginTop: 0, marginBottom: '1rem', color: '#334155' }}>
            {isEditing ? '⚡ Modify Field Metrics' : '➕ Record New Tree Vector'}
          </h3>

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem' }}>
            <label style={labelStyle}>Tree ID *
              <input type="text" name="treeId" value={formData.treeId} onChange={handleInputChange} disabled={isEditing} style={formInputStyle} placeholder="TREE-00001" required />
            </label>
            <label style={labelStyle}>Tag Number
                <input type="number" name="tagNumber" value={formData.tagNumber ?? ''} onChange={handleInputChange} style={formInputStyle} 
                placeholder="4052" />
            </label>
            <label style={labelStyle}>Scientific Name *
              <input type="text" name="scientificName" value={formData.scientificName} onChange={handleInputChange} style={formInputStyle} 
              placeholder="Quercus rubra" required />
            </label>
            <label style={labelStyle}>Common Name *
              <input type="text" name="commonName" value={formData.commonName} onChange={handleInputChange} style={formInputStyle} 
              placeholder="Red Oak" required />
            </label>
            <label style={labelStyle}>DBH (inches) *
              <input type="number" step="0.01" name="dbhInches" value={formData.dbhInches || ''} onChange={handleInputChange} style={formInputStyle} placeholder="14.50" required />
            </label>
            <label style={labelStyle}>Total Height (ft)
              <input type="number" step="0.01" name="totalHeightFt" value={formData.totalHeightFt ?? ''} onChange={handleInputChange} style={formInputStyle} placeholder="65.20" />
            </label>
            <label style={labelStyle}>Canopy Radius (ft)
              <input type="number" step="0.01" name="canopyRadiusFt" value={formData.canopyRadiusFt ?? ''} onChange={handleInputChange} style={formInputStyle} placeholder="22.00" />
            </label>
            <label style={labelStyle}>Height to Crown Base (ft)
              <input type="number" step="0.01" name="heightToCrownBaseFt" value={formData.heightToCrownBaseFt ?? ''} onChange={handleInputChange} style={formInputStyle} placeholder="15.00" />
            </label>
            <label style={labelStyle}>Number of Trunks
              <input type="number" name="numberOfTrunks" value={formData.numberOfTrunks ?? ''} onChange={handleInputChange} style={formInputStyle} placeholder="2" />
            </label>
            <label style={labelStyle}>GPS Coordinates *
              <input type="text" name="gpsCoordinates" value={formData.gpsCoordinates} onChange={handleInputChange} style={formInputStyle} placeholder="37.7749,-122.4194" required />
            </label>
            <label style={labelStyle}>Condition Class
              <select name="conditionClass" value={formData.conditionClass ?? ''} onChange={handleInputChange} style={formInputStyle}>
                <option value="">-- Unset --</option>
                <option value="Excellent">Excellent</option>
                <option value="Good">Good</option>
                <option value="Fair">Fair</option>
                <option value="Poor">Poor</option>
              </select>
            </label>
            <label style={labelStyle}>Dieback Percentage
              <select name="diebackPercentage" value={formData.diebackPercentage ?? ''} onChange={handleInputChange} style={formInputStyle}>
                <option value="">-- Unset --</option>
                <option value="0-10%">0-10%</option>
                <option value="11-25%">11-25%</option>
                <option value="26-50%">26-50%</option>
                <option value="50%+">50%+</option>
              </select>
            </label>
            <label style={labelStyle}>Pest/Disease Present
              <select name="pestDiseasePresent" value={formData.pestDiseasePresent ?? ''} onChange={handleInputChange} style={formInputStyle}>
                <option value="">-- Unset --</option>
                <option value="None">None</option>
                <option value="Spotted Lanternfly">Spotted Lanternfly</option>
                <option value="Emerald Ash Borer">Emerald Ash Borer</option>
                <option value="Oak Wilt">Oak Wilt</option>
                <option value="Other">Other</option>
              </select>
            </label>
            <label style={labelStyle}>structuralDefects
              <select name="structuralDefects" value={formData.structuralDefects ?? ''} onChange={handleInputChange} style={formInputStyle}>
                <option value="">-- Unset --</option>
                <option value="None">None</option>
                <option value="Potholes">Potholes</option>
                <option value="Cracks">Cracks</option>
                <option value="Other">Other</option>
              </select>
            </label>
            <label style={labelStyle}>gpsCoordinates
              <input type="text" name="gpsCoordinates" value={formData.gpsCoordinates} onChange={handleInputChange} style={formInputStyle} 
              placeholder="37.7749,-122.4194" />
            </label>
            <label style={labelStyle}>Land Use Type
              <select name="landUseType" value={formData.landUseType ?? ''} onChange={handleInputChange} style={formInputStyle}>
                <option value="">-- Unset --</option>
                <option value="Riparian Buffer">Riparian Buffer</option>
                <option value="Urban Park">Urban Park</option>
                <option value="Street Tree">Street Tree</option>
                <option value="Forested Wetland">Forested Wetland</option>
              </select>
            </label>
            <label style={labelStyle}>soilMoistureRegime
              <select name="soilMoistureRegime" value={formData.soilMoistureRegime ?? ''} onChange={handleInputChange} style={formInputStyle}>
                <option value="">-- Unset --</option>
                <option value="Well Drained (Dry)">Dry</option>
                <option value="Poorly Drained (Wet)">Wet</option>
                <option value="Moderately Drained">Moist</option>
              </select>
            </label>
            <label style={labelStyle}>surroundingSurface
              <select name="surroundingSurface" value={formData.surroundingSurface ?? ''} onChange={handleInputChange} style={formInputStyle}>
                <option value="">-- Unset --</option>
                <option value="Turf Grass">Turf Grass</option>
                <option value="Soil/Mulch">Soil/Mulch</option>
                <option value="Permeable Pavers">Permeable Pavers</option>
                <option value="Concrete/Asphalt">Concrete/Asphalt</option>
              </select>
            </label>
            <label style={labelStyle}>insertDate
              <input type="date" name="insertDate" value={formData.insertDate} onChange={handleInputChange} style={formInputStyle} />
            </label>
            <label style={labelStyle}>lastUpdate
              <input type="date" name="lastUpdate" value={formData.lastUpdate} onChange={handleInputChange} style={formInputStyle} />
            </label>
            <label style={labelStyle}>teamMembers
              <input type="text" name="teamMembers" value={formData.teamMembers} onChange={handleInputChange} style={formInputStyle} 
              placeholder="None" />
            </label>        
            <label style={labelStyle}>Field Notes
              <textarea name="notes" value={formData.notes ?? ''} onChange={handleInputChange} style={{ ...formInputStyle, height: '60px' }} placeholder="None" />
            </label>
            <label style={labelStyle}>Tree Photo
              <input type="file" accept="image/*" onChange={handleFileChange} style={formInputStyle} />
              {selectedFile && (
                <span style={{ fontSize: '0.75rem', color: '#334155' }}>Selected: {selectedFile.name}</span>
              )}
              {!selectedFile && formData.photoUrl && (
                <img src={formData.photoUrl} alt="Current tree photo" style={{ width: '80px', height: '80px', objectFit: 'cover', borderRadius: '4px', marginTop: '4px' }} />
              )}
            </label>
            <button 
            type="submit" 
            disabled={isLoading} 
            style={{ flex: 1, padding: '0.6rem', background: isUploading ? '#94a3b8' : '#15803d', color: '#fff', border: 'none', borderRadius: '4px', cursor: isUploading ? 'not-allowed' : 'pointer', fontWeight: 'bold' }}
            >
                {isUploading ? 'Uploading to S3...' : isEditing ? 'Commit Updates' : 'Publish Entry'}
                {isEditing && (<button type="button" onClick={() => { setIsEditing(false); setFormData(BLANK_FORM); setSelectedFile(null); }} style={{ padding: '0.6rem', background: '#64748b', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>Cancel</button>)}

            </button>
          </form>
        </div>
        {/* ==========================================
          RIGHT COLUMN: THE DATA DASHBOARD TABLE PRESENTATION GRID
         ========================================== */}
                <div style={{ overflowX: 'auto', background: '#fff', borderRadius: '8px', border: '1px solid #e2e8f0', width: '100%' }}>
        {isLoading ? (
            <div style={{ padding: '4rem', textAlign: 'center', color: '#475569', fontWeight: '500' }}>
            Streaming records dataset from canopy_dashboard...
            </div>
        ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.8rem' }}>
            <thead>
                <tr style={{ background: '#0f172a', color: '#fff' }}>
                <th style={{ padding: '12px 10px', fontWeight: '600' }}>Image</th>
                <th style={{ padding: '12px 10px', fontWeight: '600' }}>Tree ID</th>
                <th style={{ padding: '12px 10px', fontWeight: '600' }}>Taxonomy / Common Name</th>
                <th style={{ padding: '12px 10px', fontWeight: '600' }}>DBH</th>
                <th style={{ padding: '12px 10px', fontWeight: '600' }}>Vigor Status</th>
                <th style={{ padding: '12px 10px', fontWeight: '600' }}>Hydric Regime</th>
                <th style={{ padding: '12px 10px', fontWeight: '600' }}>Coordinates</th>
                <th style={{ padding: '12px 10px', fontWeight: '600' }}>Team Crew</th>
                <th style={{ padding: '12px 10px', fontWeight: '600', textAlign: 'center' }}>Actions Management</th>
                </tr>
            </thead>
            <tbody>
                {filteredTrees.length > 0 ? (
                filteredTrees.map((tree) => (
                    <tr key={tree.treeId} style={{ borderBottom: '1px solid #e2e8f0' }}>
                    
                    {/* CloudFront serve/render block */}
                    <td style={{ padding: '12px 10px', verticalAlign: 'middle' }}>
                        {tree.photoUrl ? (
                        <img 
                            src={tree.photoUrl} 
                            alt={tree.commonName} 
                            style={{ width: '50px', height: '50px', objectFit: 'cover', borderRadius: '4px', border: '1px solid #cbd5e1' }} 
                        />
                        ) : (
                        <div style={{ width: '50px', height: '50px', background: '#f8fafc', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '4px', fontSize: '0.6rem', color: '#94a3b8', border: '1px dashed #cbd5e1' }}>
                            No Photo
                        </div>
                        )}
                    </td>
                    
                    <td style={{ padding: '12px 10px', verticalAlign: 'middle', fontWeight: 'bold', color: '#1e293b' }}>
                        {tree.treeId}
                    </td>
                    
                    <td style={{ padding: '12px 10px', verticalAlign: 'middle' }}>
                        <div style={{ fontWeight: '700', color: '#0f172a' }}>{tree.commonName}</div>
                        <div style={{ fontStyle: 'italic', color: '#64748b' }}>{tree.scientificName}</div>
                    </td>
                    
                    <td style={{ padding: '12px 10px', verticalAlign: 'middle' }}>
                        {tree.dbhInches ? `${tree.dbhInches}"` : 'N/A'}
                    </td>
                    
                    <td style={{ padding: '12px 10px', verticalAlign: 'middle' }}>
                        <span style={{
                        background: tree.conditionClass === 'Dead' || tree.conditionClass === 'Poor' ? '#fee2e2' : '#f0fdf4',
                        color: tree.conditionClass === 'Dead' || tree.conditionClass === 'Poor' ? '#991b1b' : '#166534',
                        padding: '2px 6px', borderRadius: '4px', fontWeight: '600', fontSize: '0.75rem'
                        }}>
                        {tree.conditionClass || 'Unassigned'}
                        </span>
                    </td>
                    
                    <td style={{ padding: '12px 10px', verticalAlign: 'middle' }}>
                        {tree.soilMoistureRegime || 'Unassigned'}
                    </td>
                    
                    <td style={{ padding: '12px 10px', verticalAlign: 'middle', fontFamily: 'monospace' }}>
                        {tree.gpsCoordinates}
                    </td>
                    
                    <td style={{ padding: '12px 10px', verticalAlign: 'middle' }}>
                        {tree.teamMembers}
                    </td>
                    
                    {/* CRUD triggers */}
                    <td style={{ padding: '12px 10px', verticalAlign: 'middle', textAlign: 'center', whiteSpace: 'nowrap' }}>
                        <button 
                        onClick={() => startEdit(tree)} 
                        style={{ marginRight: '6px', padding: '5px 10px', background: '#2563eb', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: '500' }}
                        >
                        Modify
                        </button>
                        <button 
                        onClick={() => handleDelete(tree.treeId)} 
                        style={{ padding: '5px 10px', background: '#dc2626', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontWeight: '500' }}
                        >
                        Purge
                        </button>
                    </td>
                    
                    </tr>
                ))
                ) : (
                <tr>
                    <td colSpan={9} style={{ padding: '4rem', verticalAlign: 'middle', textAlign: 'center', color: '#64748b', fontSize: '0.9rem' }}>
                    No cataloged data logs match your chosen query text parameter.
                    </td>
                </tr>
                )}
            </tbody>
            </table>
        )}
        </div> {/* <-- End of Right Column Data Dashboard Table */}
      </div>    {/* <-- End of Parent Layout Grid Wrapper */}
    </section> /* <-- End of Main Component Section Container */                         
    );
}
                                    
const labelStyle: React.CSSProperties = { 
    fontSize: '0.8rem', 
    fontWeight: 'bold', 
    color: '#475569', 
    display: 'flex', 
    flexDirection: 'column', 
    gap: '2px' 
};

//const formInputStyle: React.CSSProperties = {width: '100%', padding: '0.45rem', marginTop: '2px', borderRadius: '4px', border: '1px solid #cbd5e1', fontSize: '0.85rem', fontWeight: 'normal', boxSizing: 'border-box'};

//const tableHeaderStyle: React.CSSProperties = { padding: '12px 10px', fontWeight: '600' };const tableCellStyle: React.CSSProperties = { padding: '12px 10px', verticalAlign: 'middle' };

//const tableCellStyle: React.CSSProperties = { padding: '12px 10px', verticalAlign: 'middle' };

// Inline presentation style configurations
const formInputStyle: React.CSSProperties = {
  width: '100%',
  padding: '0.5rem',
  marginBottom: '0.5rem',
  border: '1px solid #e2e8f0',
  borderRadius: '4px',
  fontSize: '0.9rem',
  color: '#1e293b',
};

/*const tableHeaderStyle: React.CSSProperties = {
  padding: '0.5rem',
  border: '1px solid #e2e8f0',
  fontSize: '0.9rem',
  fontWeight: 'bold',
  color: '#1e293b',
};

const tableCellStyle: React.CSSProperties = {
  padding: '0.5rem',
  border: '1px solid #e2e8f0',
  fontSize: '0.9rem',
  color: '#1e293b',
}; */
