import React, { useState } from 'react';
import { TreeInventoryRecord } from '../types/tree_inventory_schema';

interface TreeCardProps {
  tree: TreeInventoryRecord;
}

// Fallback visual asset if CloudFront returns 404 or field data is missing
const PLACEHOLDER_IMAGE = "https://rivanna.org";

export const TreePhotoCard: React.FC<TreeCardProps> = ({ tree }) => {
  const [imgSrc, setImgSrc] = useState<string>(tree.photoUrl || PLACEHOLDER_IMAGE);

  // If the CloudFront image fails to load or is deleted, swap to placeholder smoothly
  const handleImageError = () => {
    if (imgSrc !== PLACEHOLDER_IMAGE) {
      setImgSrc(PLACEHOLDER_IMAGE);
    }
  };

  return (
    <div className="max-w-sm rounded-lg overflow-hidden shadow-md border border-gray-200 bg-white">
      <div className="relative h-48 w-full bg-gray-100">
        <img
          className="w-full h-full object-cover"
          src={imgSrc}
          alt={`${tree.commonName} (${tree.scientificName})`}
          onError={handleImageError}
          loading="lazy" // Native browser optimization for dashboard scrolling performance
        />
        <div className="absolute top-2 left-2 bg-green-700 text-white text-xs font-bold px-2 py-1 rounded">
          {tree.treeId}
        </div>
      </div>
      
      <div className="p-4">
        <h3 className="font-bold text-lg text-gray-900">{tree.commonName}</h3>
        <p className="text-sm text-gray-500 italic mb-2">{tree.scientificName}</p>
        
        <div className="grid grid-cols-2 gap-2 text-xs text-gray-700 border-t pt-2">
          <div><strong>DBH:</strong> {tree.dbhInches} in</div>
          <div><strong>Height:</strong> {tree.totalHeightFt ? `${tree.totalHeightFt} ft` : 'N/A'}</div>
          <div><strong>Condition:</strong> {tree.conditionClass || 'Unknown'}</div>
          <div><strong>Soil:</strong> {tree.soilMoistureRegime || 'Unknown'}</div>
        </div>
      </div>
    </div>
  );
};

