from bson.objectid import ObjectId
import logging

from utils.mongo_tenant import get_tenant_database, open_grid_file


def sync_study_material_to_mongo(material):
    """
    Sync study material data to MongoDB.

    Args:
        material (StudyMaterial): The SQLAlchemy StudyMaterial model instance to sync.

    Returns:
        bool: True if sync is successful, False otherwise.
    """
    if not material:
        logging.error("Error: StudyMaterial object is None. Cannot sync to MongoDB.")
        return False

    try:
        mongo_db = get_tenant_database(material.tenant_id)
        mongo_data = {
            "material_id": material.id,
            "tenant_id": material.tenant_id,
            "title": material.title,
            "description": material.description,
            "course_time": material.course_time,
            "max_time": material.max_time,
            "created_at": material.created_at.isoformat() if material.created_at else None,
            "file_ids": [],
        }

        for file_entry in material.files or []:
            try:
                file_id, filename = file_entry.split('|', 1)
                grid_file, _ = open_grid_file(file_id, material.tenant_id)

                mongo_data["file_ids"].append({
                    "file_id": str(grid_file._id),
                    "filename": grid_file.filename,
                    "content_type": grid_file.content_type or "unknown",
                    "length": grid_file.length,
                })

                logging.info(f"File {filename} (ID: {file_id}) added to MongoDB metadata for material {material.id}.")

            except Exception as e:
                logging.error(f"Error processing file entry {file_entry} for material {material.id}: {e}")
                continue

        result = mongo_db.study_materials.update_one(
            {"material_id": material.id},
            {"$set": mongo_data},
            upsert=True,
        )
        logging.info(f"Study material {material.id} synced to {mongo_db.name}. Result: {result.raw_result}")
        return True

    except Exception as e:
        logging.error(f"Error syncing study material {material.id} to MongoDB: {e}")
        return False
