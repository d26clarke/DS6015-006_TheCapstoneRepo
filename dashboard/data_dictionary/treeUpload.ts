import { Router, Request, Response } from 'express';
import multer from 'multer';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { Pool } from 'pg';

const router = Router();

// 1. Initialize AWS S3 Client & PostgreSQL Pool
const s3 = new S3Client({ region: process.env.AWS_REGION });
const pgPool = new Pool({ connectionString: process.env.DATABASE_URL });

const CLOUDFRONT_DOMAIN = process.env.CLOUDFRONT_DOMAIN; // e.g., 'https://rivanna.org'
const BUCKET_NAME = process.env.AWS_S3_BUCKET_NAME;

// 2. Configure Multer to retain file buffers in memory
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 10 * 1024 * 1024 }, // 10MB maximum file size limit
  fileFilter: (req, file, cb) => {
    if (file.mimetype.startsWith('image/')) {
      cb(null, true);
    } else {
      cb(new Error('Only image files are permitted.'));
    }
  }
});

// 3. Post Route for uploading images and saving to database
router.post('/trees/:treeId/upload-photo', upload.single('photo'), async (req: Request, res: Response): Promise<void> => {
  const { treeId } = req.params;
  const file = req.file;

  if (!file) {
    res.status(400).json({ error: 'No image file uploaded.' });
    return;
  }

  try {
    // Generate a unique, deterministic object path inside the S3 bucket
    const fileExtension = file.originalname.split('.').pop() || 'jpg';
    const s3Key = `trees/${treeId}_${Date.now()}.${fileExtension}`;

    // Upload directly to S3
    await s3.send(
      new PutObjectCommand({
        Bucket: BUCKET_NAME,
        Key: s3Key,
        Body: file.buffer,
        ContentType: file.mimetype,
      })
    );

    // Formulate the target CloudFront URL
    const cloudFrontUrl = `${CLOUDFRONT_DOMAIN}/${s3Key}`;

    // Update the record inside PostgreSQL
    const queryText = `
      UPDATE tree_inventory 
      SET photo_url = $1, last_update = CURRENT_DATE 
      WHERE tree_id = $2
      RETURNING *;
    `;
    const dbResult = await pgPool.query(queryText, [cloudFrontUrl, treeId]);

    if (dbResult.rowCount === 0) {
      res.status(404).json({ error: `Tree record with ID ${treeId} not found.` });
      return;
    }

    res.status(200).json({
      message: 'Photo uploaded successfully.',
      updatedTree: dbResult.rows[0],
    });
  } catch (error) {
    console.error('Upload execution failure:', error);
    res.status(500).json({ error: 'Internal server upload or database failure.' });
  }
});

export default router;

