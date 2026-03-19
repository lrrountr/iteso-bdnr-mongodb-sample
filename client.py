#!/usr/bin/env python3
import argparse
import csv
import logging
import os
import requests


# Set logger
log = logging.getLogger()
log.setLevel('INFO')
handler = logging.FileHandler('books.log')
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
log.addHandler(handler)

# Read env vars related to API connection
BOOKS_API_URL = os.getenv("BOOKS_API_URL", "http://localhost:8000")



def print_book(book):
    for k in book.keys():
        print(f"{k}: {book[k]}")
    print("="*50)


def list_books(rating):
    suffix = "/books"
    endpoint = BOOKS_API_URL + suffix
    params = {
        "rating": rating
    }
    response = requests.get(endpoint, params=params)
    if response.ok:
        json_resp = response.json()
        for book in json_resp:
            print_book(book)
    else:
        print(f"Error: {response}")


def get_book_by_id(id):
    suffix = f"/books/{id}"
    endpoint = BOOKS_API_URL + suffix
    response = requests.get(endpoint)
    if response.ok:
        json_resp = response.json()
        print_book(json_resp)
    else:
        print(f"Error: {response}")


def load_books():
    suffix = f"/books"
    endpoint = BOOKS_API_URL + suffix
    with open("data/books.csv") as fd:
        books_csv = csv.DictReader(fd)
        for book in books_csv:
            del book["bookID"]
            book["authors"] = book["authors"].split("/")
            x = requests.post(endpoint, json=book)
            if x.ok:
                print(f"Book {book['title']} created with id {x.json()['_id']}")
            else:
                print(f"Failed to post book {x} - {book}")


def update_book(id):
    suffix = f"/books/{id}"
    endpoint = BOOKS_API_URL + suffix
    title = input("Enter new title: ")
    authors = input("Enter new authors (separated by comma): ")
    average_rating = input("Enter new average rating: ")
    isbn = input("Enter new ISBN: ")
    isbn13 = input("Enter new ISBN13: ")
    language_code = input("Enter new language code: ")
    num_pages = input("Enter new number of pages: ")
    ratings_count = input("Enter new ratings count: ")
    text_reviews_count = input("Enter new text reviews count: ")
    publication_date = input("Enter new publication date (YYYY-MM-DD): ")
    publisher = input("Enter new publisher: ")
    book = {
        "title": title,
        "authors": [author.strip() for author in authors.split(",")],
        "average_rating": float(average_rating),
        "isbn": isbn,
        "isbn13": isbn13,
        "language_code": language_code,
        "num_pages": int(num_pages),
        "ratings_count": int(ratings_count),
        "text_reviews_count": int(text_reviews_count),
        "publication_date": publication_date,
        "publisher": publisher
    }

    response = requests.put(endpoint, json=book)
    if response.ok:
        print(f"Book with id {id} updated successfully")
    else:
        print(f"Error: {response}")


def delete_book(id):
    suffix = f"/books/{id}"
    endpoint = BOOKS_API_URL + suffix
    response = requests.delete(endpoint)
    if response.ok:
        print(f"Book with id {id} deleted successfully")
    else:
        print(f"Error: {response}")


def main():
    log.info(f"Welcome to books catalog. App requests to: {BOOKS_API_URL}")

    parser = argparse.ArgumentParser()

    list_of_actions = ["load", "search", "get", "update", "delete"]
    parser.add_argument("action", choices=list_of_actions,
            help="Action to be user for the books library")
    parser.add_argument("-i", "--id",
            help="Provide a book ID which related to the book action", default=None)
    parser.add_argument("-r", "--rating",
            help="Search parameter to look for books with average rating equal or above the param (0 to 5)", default=None)

    args = parser.parse_args()

    if args.id and not args.action in ["get", "update", "delete"]:
        log.error(f"Can't use arg id with action {args.action}")
        exit(1)

    if args.rating and args.action != "search":
        log.error(f"Rating arg can only be used with search action")
        exit(1)

    if args.action == "load":
        load_books()
    elif args.action == "search":
        list_books(args.rating)
    elif args.action == "get" and args.id:
        get_book_by_id(args.id)
    elif args.action == "update":
        update_book(args.id)
    elif args.action == "delete":
        delete_book(args.id)

if __name__ == "__main__":
    main()