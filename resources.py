#!/usr/bin/env python3
import logging

import falcon
from bson.objectid import ObjectId

# Set logger
log = logging.getLogger()
log.setLevel('INFO')
handler = logging.FileHandler('books.log')
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
log.addHandler(handler)

class BookResource:
    def __init__(self, db):
        self.db = db

    async def on_get(self, req, resp, book_id):
        """Handles GET requests to retrieve a single book"""
        book = self.db.books.find_one({'_id': ObjectId(book_id)})
        if book:
            book['_id'] = str(book['_id'])
            resp.media = book
            resp.status = falcon.HTTP_200
            log.info(f"Book with id {book_id} retrieved successfully")
        else:
            resp.status = falcon.HTTP_404
            log.warning(f"Book with id {book_id} not found")

    async def on_put(self, req, resp, book_id):
        """Handles PUT requests to update a single book"""
        data = await req.media
        data = validate_book_data(data)
        result = self.db.books.update_one({'_id': ObjectId(book_id)}, {'$set': data})
        if result.matched_count:
            resp.status = falcon.HTTP_200
            log.info(f"Book with id {book_id} updated successfully")
        else:
            resp.status = falcon.HTTP_404
            log.warning(f"Book with id {book_id} not found")

    async def on_delete(self, req, resp, book_id):
        """Handles DELETE requests to delete a single book"""
        result = self.db.books.delete_one({'_id': ObjectId(book_id)})
        if result.deleted_count:
            resp.status = falcon.HTTP_200
            log.info(f"Book with id {book_id} deleted successfully")
        else:
            resp.status = falcon.HTTP_404
            log.warning(f"Book with id {book_id} not found")


class BooksResource:
    def __init__(self, db):
        self.db = db

    async def on_get(self, req, resp):
        """Handles GET requests to retrieve all books"""
        rating = req.get_param_as_float('rating')
        query = {}
        if rating is not None:
            query['average_rating'] = {'$gte': rating}
            log.info(f"Retrieving books with average rating >= {rating}")

        books = self.db.books.find(query)
        books_list = []
        for book in books:
            book['_id'] = str(book['_id'])
            books_list.append(book)
        resp.media = books_list
        resp.status = falcon.HTTP_200
        log.info(f"{len(books_list)} books retrieved successfully")

    async def on_post(self, req, resp):
        """Handles POST requests to add a new book"""
        data = await req.media
        data = validate_book_data(data)
        result = self.db.books.insert_one(data)
        data['_id'] = str(result.inserted_id)
        resp.media = data
        resp.status = falcon.HTTP_201
        log.info(f"Book {data['title']} created with id {data['_id']}")


book_types = {
    "title": str,
    "authors": list,
    "average_rating": float,
    "isbn": str,
    "isbn13": str,
    "language_code": str,
    "num_pages": int,
    "ratings_count": int,
    "text_reviews_count": int,
    "publication_date": str,
    "publisher":  str,
}

def validate_book_data(data):
    for property in book_types:
        if property not in data:
            raise falcon.HTTPBadRequest(f"Invalid data: {property} is required.")
        if book_types[property] != str:
            try:
                data[property] = book_types[property](data[property])
            except ValueError:
                raise falcon.HTTPBadRequest(f"Invalid data: {property} must be {book_types[property]}.")
    return data